import discord
from discord.ext import commands
import os
import asyncio
import logging
import math

from mega import (MegaApi, MegaRequestListener, MegaError, MegaRequest,MegaTransfer,
                  MegaUser, MegaNode)

CHANNEL_ID = 415887620871159830
logging.basicConfig(level=logging.INFO,
                        #filename='runner.log',
                        format='%(levelname)s\t%(asctime)s %(message)s')

class AppListener(MegaRequestListener):
    def __init__(self):
        self.cwd = None
        super(AppListener, self).__init__()


    def onRequestStart(self, api, request):
        logging.info('Request start ({})'.format(request.getType()))


    def onRequestFinish(self, api, request, error):
        logging.info('Request finished ({}); Result: {}'
                     .format(request, error))
        if error.getErrorCode() != MegaError.API_OK:
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
            self.cwd =api.getRootNode().copy()
        elif request_type == MegaRequest.TYPE_GET_PUBLIC_NODE:
            self.cwd =request.getPublicMegaNode()

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
    def name(self):
        return self._api.getParentNode(self._listener.cwd).getName()
    def ls(self):
        """Usage: ls [path]"""
       
        if self._listener.cwd == None:
            return 'INFO: Not logged in'
      
        nodes = self._api.getChildren(self._listener.cwd)
    
        max_name_length = max(len(nodes.get(i).getName()) for i in range(nodes.size()))
        
        output = 'Name' + ' ' * (max_name_length - 4) + '\tSize\n'
        output += '.' + ' ' * (max_name_length - 1) + '\t\n'
        
        if self._api.getParentNode(self._listener.cwd) is not None:
            output += '..' + ' ' * (max_name_length - 2) + '\t\n'

        for i in range(nodes.size()):
            node = nodes.get(i)
            node_name = node.getName()
            if node.getType() == MegaNode.TYPE_FILE:
                node_type = f'{convert_size(node.getSize())}'
            else:
                node_type = '(folder)'
            
            # Pad the node name to align the sizes
            padded_name = node_name + ' ' * (max_name_length - len(node_name))
            output += f'{padded_name}\t{node_type}\n'
                
        return '```' + output + '```'


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
            #return

        node = self._api.authorizeNode(self._listener.cwd)
        if node == None:
            print('Node not found: {}'.format(args[0]))
            return
        self._api.startDownload(node, './')#, MegaTransfer.COLLISION_CHECK_FINGERPRINT, MegaTransfer.COLLISION_RESOLUTION_NEW_WITH_N)


   

    def pwd(self, arg):
        """Usage: pwd"""
        args = arg.split()
        if len(args) != 0:
            print(self.pwd.__doc__)
            return
        if self._listener.cwd == None:
            print('INFO: Not logged in')
            return

        print('{} INFO: Current working directory: {}'
              .format(self.PROMPT, self._api.getNodePath(self._listener.cwd)))


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

    def quit(self, arg):
        """Usage: quit"""
        del self._api
        print('Bye!')
        return True
    
    #def EOF(self, line):
    #    print("Exiting...")
    #    return True

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

async def login_to_folder(api, link, listener):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, api.loginToFolder, link, listener)

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
    async def ping(self,ctx):
        await ctx.send("pong")

    @commands.command()
    async def add(self,ctx, x, y):
        result = int(x)+int(y)
        await ctx.send(f"{result}")

    @commands.command()
    async def download(self, ctx, cat, link, *, flags: str = ''):
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
        api.loginToFolder(link.strip(), listener)   
        self.megaapi = MegaSession(api,  listener)
        api = None 
        listener    =   None
        await ctx.send(self.megaapi.name())

    @commands.command()
    async def ls(self, ctx):
        if self.megaapi!=None:
            await ctx.send(self.megaapi.ls())
        else:
            await ctx.send("Start a session")
            return
        

bot = commands.Bot(command_prefix="", intents=discord.Intents.all())       
bot.add_cog(MyBot(bot))
        
@bot.event
async def on_ready():
    print("Hello")
    channel = bot.get_channel(CHANNEL_ID)
    await channel.send("Hello I'm Megabot")

async def main():
    async with bot:
        await bot.add_cog(MyBot(bot))
        await bot.start(os.getenv("TOKEN"))

if __name__ == "__main__":
    asyncio.run(main())
        
