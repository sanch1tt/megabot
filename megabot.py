import discord
from discord.ext import commands
import os
import shlex
import asyncio
import logging
import math
from requestlistener import RequestListener
from transferlistener import TransferListener
from mega import (MegaApi, MegaNode, MegaTransfer)

BOT_TOKEN = os.getenv("TOKEN")
API_KEY = os.getenv("API_KEY")
logging.basicConfig(level=logging.INFO,
                    # filename='runner.log',
                    format='%(levelname)s\t%(asctime)s %(message)s')


class MegaSession():

    def __init__(self, api, listener):
        self._api = api
        self._listener = listener
        self.backlog = []
        self.current_dls = []

    def ls(self, path, files, depth):

        if path == None:
            return 'INFO: Not logged in'
        if path.getType() == MegaNode.TYPE_FILE:
            size = f'\u001b[0;41m{convert_size(path.getSize())}\u001b[0;0m'
            files.append({"name": '\t'*depth+path.getName() +
                         '\t'+size, "handle": path.getHandle()})
        else:
            name = '\u001b[0;34m' + '\t'*depth+'./' + \
                path.getName()+'\t' + '\u001b[0;0m'
            files.append({"name": name, "handle": path.getHandle()})
            children = self._api.getChildren(path)

            for i in range(children.size()):
                self.ls(children.get(i), files, depth+1)

    def cd(self, arg):
        """Usage: cd [path]"""
        args = arg.split()
        if len(args) > 1:
            print(self.cd.__doc__)
            return
        if self._listener.cwd == None:
            print('INFO: Not logged in')
            return
        if len(args) == 0:
            self._listener.cwd = self._api.getRootNode()
            return

        node = self._api.getNodeByPath(args[0], self._listener.cwd)
        if node == None:
            print('{}: No such file or directory'.format(args[0]))
            return
        if node.getType() == MegaNode.TYPE_FILE:
            print('{}: Not a directory'.format(args[0]))
            return
        self._listener.cwd = node

    def download(self, node, save_to):
        """Usage: get remotefile"""

        if self._listener.cwd == None:
            print('INFO: Not logged in')
            return
        transfer_listener = TransferListener()
        # node = self._api.authorizeNode(node)
        if node == None:
            print('Node not found')
            return
        # , MegaTransfer.COLLISION_CHECK_FINGERPRINT, MegaTransfer.COLLISION_RESOLUTION_NEW_WITH_N)
        print(node.getName())
        self.current_dls.append(transfer_listener)
        print(len(self.current_dls))
        self._api.startDownload(
            node, save_to+'/'+node.getName(), transfer_listener)
        transfer_listener = None

    def pwd(self):
        """Usage: pwd"""
        if self._listener.cwd == None:
            print('INFO: Not logged in')
            return

        return self._listener.cwd.getName()

    def export(self, arg):
        """Usage: export path"""
        args = arg.split()
        if len(args) != 1:
            print(self.export.__doc__)
            return
        if self._listener.cwd == None:
            print('INFO: Not logged in')
            return

        node = self._api.getNodeByPath(args[0], self._listener.cwd)
        self._api.exportNode(node)

    def wait(self):
        self._listener.event.wait()

    def quit(self):
        """Usage: quit"""
        del self._listener
        del self._api
        print('Bye!')
        return True


def convert_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return "%s %s" % (s, size_name[i])


def expand_ranges(msg):
    output = set()
    for item in msg.split(','):
        if '-' in item:
            start, end = map(int, item.split('-'))
            output.update(range(start, end + 1))
        else:
            output.add(int(item))
    return output


class MyBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.mega = None

    @commands.command()
    @commands.is_owner()  # Restrict this command to the bot owner
    async def quit(self, ctx):
        print("Shutting down bot...")
        await ctx.send('Shutting down...')
        if self.mega:
            self.mega.quit()
        await self.bot.close()

    def status_text(self):
        return 'Current downloads:\n```ansi\n' + \
            os.linesep.join([tl.getStatus()
                             for tl in self.mega.current_dls])+'\n```'

    async def update_status_message_task(self, status_message):
        while not all([dl.is_finished for dl in self.mega.current_dls]):
            await status_message.edit(content=self.status_text())
            await asyncio.sleep(1)  # Update every second

    async def pause_button_task(self, ctx, status_message):
        def check(reaction, user): return reaction.message.id == status_message.id and user == ctx.message.author and str(
            reaction.emoji) in ['▶', '⏸']
        pause = False
        while True:
            reaction, user = await bot.wait_for('reaction_add', check=check)
            pause = not pause
            await status_message.clear_reactions()
            self.mega._api.pauseTransfers(pause)
            if pause:
                await status_message.add_reaction('▶')
            else:
                await status_message.add_reaction('⏸')

    async def status_message_task(self, ctx):
        status_message = await ctx.send("Starting downloads...")
        await status_message.add_reaction('⏸')
        update_status_task = asyncio.create_task(
            self.update_status_message_task(status_message))
        pause_button_task = asyncio.create_task(
            self.pause_button_task(ctx, status_message))
        await update_status_task
        pause_button_task.cancel()
        await status_message.edit(content=self.status_text())
        if self.mega:
            self.mega.current_dls.clear()

    @commands.command()
    async def ping(self, ctx):
        await ctx.send("pong")

    @commands.command()
    async def dl(self, ctx, cat, link, *, flags: str = ''):
        match cat:
            case 'f':
                dir = '/downloads'
            case _:
                await ctx.send("Category doesn't exist")
                return
        split_flags = shlex.split(flags)
        if '--sub' in split_flags:
            await ctx.send("Select the directory")
        if '--dir' in split_flags:
            try:
                dir += '/'+split_flags[split_flags.index('--dir')+1].strip()
                os.makedirs(dir, exist_ok=True)
            except:
                await ctx.send("Not a correct directory")
                return
        api = MegaApi(API_KEY, None, None, 'megabot session')
        listener = RequestListener()
        print(link)
        self.mega = MegaSession(api,  listener)
        if any(f in link for f in ["folder", "#F!"]):
            api.loginToFolder(link.strip(), listener)
        else:
            api.getPublicNode(link.strip(), listener)
        self.mega.wait()
        api = None
        listener = None
        if any(f in link for f in ["folder", "#F!"]):
            await ctx.send(f"Opened  folder `{self.mega.pwd()}`")
            try:
                files = []
                self.mega.ls(self.mega._listener.cwd, files, 0)
                output = '```ansi'+os.linesep + \
                    os.linesep.join(str(i)+n["name"]
                                    for i, n in enumerate(files)) + '```'
                await ctx.send(output)
                await ctx.send('Choose files to download')
            except:
                await ctx.send("Couldn't open `" + link + '`')
                self.mega = None
                return
            self.mega._api.authorizeNode(self.mega._listener.cwd)
            try:
                def check(
                    m): return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id
                msg = await bot.wait_for('message', timeout=60.0, check=check)
                # self.mega._api.authorizeNode(self.mega._listener.cwd)

            except asyncio.TimeoutError:
                await ctx.send('You took too long to respond! Please try again.')
                return
            for n in expand_ranges(msg.content):
                node = self.mega._api.getNodeByHandle(files[n]["handle"])
                node = self.mega._api.authorizeNode(node)
                print(node.getName())
                self.mega.download(node, dir)
                # If this is the first download, start the status updates
                if len(self.mega.current_dls) == 1:
                    asyncio.create_task(self.status_message_task(ctx))
        else:
            files = []
            self.mega.ls(self.mega._listener.cwd, files, 0)
            question = await ctx.send("Found file:\n```ansi\n " + files[0]["name"] + "``` Do you want to download?")
            await question.add_reaction('✅')
            await question.add_reaction('❌')
            def check(reaction, user): return reaction.message.id == question.id and user == ctx.message.author and str(
                reaction.emoji) in ['✅', '❌']
            try:
                reaction, user = await bot.wait_for('reaction_add', timeout=60.0, check=check)
                match str(reaction.emoji):
                    case '✅':
                        self.mega.download(self.mega._listener.cwd, dir)
                        # If this is the first download, start the status updates
                        if len(self.mega.current_dls) == 1:
                            asyncio.create_task(self.status_message_task(ctx))
                    case _:
                        await self.cancel(ctx)
            except asyncio.TimeoutError:
                await ctx.send('You took too long to respond! Please try again.')
                return
            except Exception as e:
                logging.error(f"Error downloding: {e}")
                return

    @commands.command()
    async def ls(self, ctx):
        if self.mega != None:
            files = []
            self.mega.ls(self.mega._listener.cwd, files, 0)
            output = '```ansi'+os.linesep + \
                os.linesep.join(str(i)+' '+n["name"]
                                for i, n in enumerate(files)) + '```'
            await ctx.send(output)
        else:
            await ctx.send("Start a session")
            return

    @commands.command()
    async def cancel(self, ctx):
        if self.mega:
            self.mega._api.cancelTransfers(MegaTransfer.TYPE_DOWNLOAD)
            await ctx.send(f"Cancelling the download of `{self.mega.pwd()}`")
            self.mega.current_dls.clear()
            await asyncio.sleep(1)
            self.mega = None
        else:
            await ctx.send("No session open")


bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())


@bot.event
async def on_ready():
    print("Starting bot...")
    try:
        for guild in bot.guilds:
            for channel in guild.text_channels:
                if channel.permissions_for(guild.me).send_messages:
                    await channel.send("Hello I'm Megabot")
    except:
        print("Error starting the bot")


async def main():
    async with bot:
        await bot.add_cog(MyBot(bot))
        await bot.start(BOT_TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
