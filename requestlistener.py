import threading
import logging
from mega import ( MegaRequestListener, MegaError, MegaRequest)

class RequestListener(MegaRequestListener):
    def __init__(self):
        self.cwd = None
        self.event = threading.Event()
        super(RequestListener, self).__init__()

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
            self.cwd = api.getRootNode()
        elif request_type == MegaRequest.TYPE_GET_PUBLIC_NODE:
            self.cwd = request.getPublicMegaNode()

        if request_type != MegaRequest.TYPE_LOGIN and request_type != MegaRequest.TYPE_DELETE:
            self.event.set()
            self.event.clear()

    def onRequestTemporaryError(self, api, request, error):
        logging.info('Request temporary error ({}); Error: {}'
                     .format(request, error))