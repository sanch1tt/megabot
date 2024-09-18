import discord
from discord.ext import commands
import os
import asyncio
import threading
import logging
import math

from mega import (MegaApi, MegaRequestListener, MegaError, MegaRequest, MegaTransfer,
                  MegaUser, MegaNode)

CHANNEL_ID = 415887620871159830
logging.basicConfig(level=logging.INFO,
                    # filename='runner.log',
                    format='%(levelname)s\t%(asctime)s %(message)s')


class AppListener(MegaRequestListener):
    def __init__(self):
        self.cwd = None
        self.event = threading.Event()
        super(AppListener, self).__init__()

    def onRequestStart(self, api, request):
        logging.info('Request start ({})'.format(request.getType()))

    def onRequestFinish(self, api, request, error):
        logging.info('Request finished ({}); Result: {}'
                     .format(request, error))
        if error.getErrorCode() != MegaError.API_OK:
            self.event.set()
            self.event.clear()
            return

        request_type = request.getType()
        if request_type == MegaRequest.TYPE_LOGIN:
            api.fetchNodes(self)
        elif request_type == MegaRequest.TYPE_EXPORT:
            logging.info('Exported link: {}'.format(request.getLink()))
        elif request_type == MegaRequest.TYPE_ACCOUNT_DETAILS:
            account_details = request.getMegaAccountDetails()
            logging.info('Account details received')
            logging.info('Account e-mail: {}'.format(api.getMyEmail()))
            logging.info('Storage: {} of {} ({} %)'
                         .format(account_details.getStorageUsed(),
                                 account_details.getStorageMax(),
                                 100 * account_details.getStorageUsed()
                                 / account_details.getStorageMax()))
            logging.info('Pro level: {}'.format(account_details.getProLevel()))
        elif request_type == MegaRequest.TYPE_FETCH_NODES:
            self.cwd = api.getRootNode().copy()
        elif request_type == MegaRequest.TYPE_GET_PUBLIC_NODE:
            self.cwd = request.getPublicMegaNode()

        if request_type != MegaRequest.TYPE_LOGIN and request_type != MegaRequest.TYPE_DELETE:
            self.event.set()
            self.event.clear()

    def onRequestTemporaryError(self, api, request, error):
        logging.info('Request temporary error ({}); Error: {}'
                     .format(request, error))

    def onTransferFinish(self, api, transfer, error):
        logging.info('Transfer finished ({}); Result: {}'
                     .format(transfer, transfer.getFileName(), error))

    def onTransferUpdate(self, api, transfer):
        logging.info('Transfer update ({} {});'
                     ' Progress: {} KB of {} KB, {} KB/s'
                     .format(transfer,
                             transfer.getFileName(),
                             transfer.getTransferredBytes() / 1024,
                             transfer.getTotalBytes() / 1024,
                             transfer.getSpeed() / 1024))

    def onTransferTemporaryError(self, api, transfer, error):
        logging.info('Transfer temporary error ({} {}); Error: {}'
                     .format(transfer, transfer.getFileName(), error))

    def onUsersUpdate(self, api, users):
        if users != None:
            logging.info('Users updated ({})'.format(users.size()))

    def onNodesUpdate(self, api, nodes):
        if nodes != None:
            logging.info('Nodes updated ({})'.format(nodes.size()))
        else:
            self._shell.cwd = api.getRootNode()


class MegaSession(MegaRequestListener):

    def __init__(self, api, listener):
        self._api = api
        self._listener = listener
        super(MegaSession, self).__init__()

    def ls(self, path, files, depth):

        if path == None:
            return 'INFO: Not logged in'
        if path.getType() == MegaNode.TYPE_FILE:
            node_type = f'\u001b[0;41m{convert_size(path.getSize())}\u001b[0;0m'
            files.append({"name":'\t'*depth+path.getName()+'\t'+node_type, "dir": path})
        else:
            name = '\u001b[0;34m' + '\t'*depth+'./'+path.getName()+'\t' + '\u001b[0;0m'
            files.append({"name":name, "dir": path})
            children = self._api.getChildren(path)

            for i in range(children.size()):
                self.ls(children.get(i),files,depth+1)
        

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

    def get(self, arg):
        """Usage: get remotefile"""
        args = arg.split()
        if len(args) != 2:
            print(self.get.__doc__)
            return
        if self._listener.cwd == None:
            print('INFO: Not logged in')
            # return

        node = self._api.authorizeNode(self._listener.cwd)
        if node == None:
            print('Node not found: {}'.format(args[0]))
            return
        # , MegaTransfer.COLLISION_CHECK_FINGERPRINT, MegaTransfer.COLLISION_RESOLUTION_NEW_WITH_N)
        self._api.startDownload(node, './')

    def pwd(self):
        """Usage: pwd"""
        if self._listener.cwd == None:
            print('INFO: Not logged in')
            return

        return self._api.getNodePath(self._listener.cwd)

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

    def quit(self, arg):
        """Usage: quit"""
        del self._api
        print('Bye!')
        return True

    def exit(self, arg):
        """Usage: exit"""
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
    for item in msg.content.split(','):
        if '-' in item:
            start, end = map(int, item.split('-'))
            output.update(range(start, end + 1))
        else:
            output.add(int(item))
    return output

class MyBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.megaapi = None

    @commands.command()
    @commands.is_owner()  # Restrict this command to the bot owner
    async def quit(self, ctx):
        await ctx.send('Shutting down...')
        await self.bot.close()

    @commands.command()
    async def ping(self, ctx):
        await ctx.send("pong")

    @commands.command()
    async def add(self, ctx, x, y):
        result = int(x)+int(y)
        await ctx.send(f"{result}")

    @commands.command()
    async def dl(self, ctx, cat, link, *, flags: str = ''):
        match cat:
            case 'f':
                dir = '/downloads'
            case _:
                await ctx.send("Category doesn't exist")
                return
        if '--sub' in flags.split():
            await ctx.send("Select the directory")

        api = MegaApi('ox8xnQZL', None, None, 'megabot session')
        listener = AppListener()
        print(link)
        self.megaapi = MegaSession(api,  listener)
        if any(f in link for f in ["folder", "#F!"]):
            api.loginToFolder(link.strip(), listener)
        else:
            api.getPublicNode(link.strip(), listener)
        self.megaapi.wait()
        api = None
        listener = None
        if any(f in link for f in ["folder", "#F!"]):
            await ctx.send(f"Opened  folder `{self.megaapi.pwd()}`")
          
            try:
                await ctx.send("Opened  folder `" + self.megaapi.pwd() +"`")
                files = []
                self.megaapi.ls(self.megaapi._listener.cwd, files,0)
                output = '```ansi'+os.linesep+os.linesep.join(str(i)+n["name"] for i,n in enumerate(files)) + '```'
                await ctx.send( output )
            except:
                await ctx.send("Couldn't open `" + link + '`')
                self.megaapi = None
                return 0
            try:
                msg = await bot.wait_for('message', timeout=60.0)
                print(expand_ranges(msg))
            except asyncio.TimeoutError:
                await ctx.send('You took too long to respond! Please try again.')
        else:
            await ctx.send("Opened  file `" + self.megaapi._listener.cwd.getName() +"`")
     

    @commands.command()
    async def ls(self, ctx):
        if self.megaapi != None:
            files = []
            self.megaapi.ls(self.megaapi._listener.cwd, files,0)
            output = '```ansi'+os.linesep+os.linesep.join(str(i)+n["name"] for i,n in enumerate(files)) + '```'
            await ctx.send( output )
        else:
            await ctx.send("Start a session")
            return

    @commands.command()
    async def cancel(self, ctx):
        await ctx.send("Cancelling the download of " + self.megaapi.pwd())
        self.megaapi = None


bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())
bot.add_cog(MyBot(bot))


@bot.event
async def on_ready():
    print("Hello")
    channel = bot.get_channel(CHANNEL_ID)
    await channel.send("Hello I'm Megabot")
    
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return
    # Process commands
    await bot.process_commands(message)

async def main():
    async with bot:
        await bot.add_cog(MyBot(bot))
        await bot.start(os.getenv("TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
