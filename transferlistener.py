import time
import logging
from mega import (MegaTransferListener, MegaError, MegaTransfer)


class TransferListener(MegaTransferListener):
    def __init__(self):
        self.is_finished = False
        self.is_paused = False
        self.error = None
        self.transfer_name = None
        self.speed = None
        self.progress = 0
        self.start = None
        super(TransferListener, self).__init__()

    def onTransferStart(self, api, transfer):
        filename = transfer.getFileName()
        if len(filename) > 18:
            self.transfer_name = filename[:15] + '...'
        else:
            self.transfer_name = filename + ' ' * (18-len(filename))
        self.start = time.time()  # time estimate start
        logging.info('Transfer start ({})'.format(transfer.getType()))

    def onTransferFinish(self, api, transfer, error):
        self.is_finished = True
        if error.getErrorCode() != MegaError.API_OK:
            self.error = error.toString()
        logging.info('Transfer finished ({}); Result: {}'
                     .format(transfer, transfer.getFileName(), error))

    def onTransferTemporaryError(self, api, transfer, error):
        try:
            self.error = error.toString()
            logging.info('Transfer temporary error ({} {}); Error: {}'
                         .format(transfer, transfer.getFileName(), error))
            if error.getErrorCode() == MegaError.API_EINCOMPLETE:
                logging.info('Download incomplete, retrying...')
                #api.retryTransfer(transfer)
            else:
                logging.warning(f'Unhandled error code: {error}')
        except Exception as e:
            logging.error(f"Error in onTransferTemporaryError: {e}")
            logging.debug(f"Error object: {error}, Type: {type(error)}")

    def onTransferUpdate(self, api, transfer):
        self.speed = transfer.getSpeed()
        self.progress = transfer.getTransferredBytes()/transfer.getTotalBytes()
        logging.info('Transfer update ({} {});'
                     ' Progress: {} KB of {} KB, {} KB/s'
                     .format(transfer,
                             transfer.getFileName(),
                             transfer.getTransferredBytes() / 1024,
                             transfer.getTotalBytes() / 1024,
                             transfer.getSpeed() / 1024))

    def getStatus(self, size=25):
        if self.error:
            print(self.error)
            return f'{self.transfer_name}: \u001b[0;31m{self.error}\u001b[0;0m'
        if self.is_finished:
            return f"{self.transfer_name} is done downloading"
        x = int(size*self.progress)
        if self.progress == 0:
            time_str = 'inf'
        else:
            remaining = (time.time() - self.start) * \
                (1-self.progress)/self.progress
            mins, sec = divmod(remaining, 60)
            time_str = f"{int(mins):02}:{int(sec):02}"
        return f"{self.transfer_name} Speed: {(self.speed/(1024*1024)):0.2f} MB/s [\u001b[0;31m{u'█'*x}\u001b[0;0m{u'▒'*(size-x)}] {int(self.progress*100)} % Est. {time_str}"
