import base64
import zmq
import re
from cloudasr.messages import WorkerRequestMessage, MasterResponseMessage, RecognitionRequestMessage, ResultsMessage

def create_frontend_worker(master_address):
    context = zmq.Context()
    master_socket = context.socket(zmq.REQ)
    master_socket.connect(master_address)
    worker_socket = context.socket(zmq.REQ)
    decoder = Base64Decoder()

    return FrontendWorker(master_socket, worker_socket, decoder)


class FrontendWorker:
    def __init__(self, master_socket, worker_socket, decoder):
        self.master_socket = master_socket
        self.worker_socket = worker_socket
        self.decoder = decoder

    def recognize_batch(self, data, headers):
        self.validate_headers(headers)
        self.connect_to_worker(data["model"])
        response = self.recognize_batch_on_worker(data)

        return response

    def connect_to_worker(self, model):
        self.worker_address = self.get_worker_address_from_master(model)
        self.worker_socket.connect(self.worker_address)

    def recognize_chunk(self, data):
        chunk = self.decoder.decode(data)
        message = self.send_request_to_worker(chunk, "ONLINE", has_next = True)
        response = self.read_response_from_worker()

        return self.format_interim_response(response)

    def validate_headers(self, headers):
        if "Content-Type" not in headers:
            raise MissingHeaderError()

        if not re.match("audio/x-wav; rate=\d+;", headers["Content-Type"]):
            raise MissingHeaderError()

    def get_worker_address_from_master(self, model):
        request = WorkerRequestMessage()
        request.model = model

        self.master_socket.send(request.SerializeToString())
        response = MasterResponseMessage()
        response.ParseFromString(self.master_socket.recv())

        if response.status == MasterResponseMessage.SUCCESS:
            return response.address
        else:
            raise NoWorkerAvailableError()

    def recognize_batch_on_worker(self, data):
        self.send_request_to_worker(data["wav"], "BATCH", has_next = False)
        response = self.read_response_from_worker()
        self.worker_socket.disconnect(self.worker_address)

        return self.format_final_response(response)

    def send_request_to_worker(self, data, type, has_next = False):
        request = self.make_request_message(data, type, has_next)
        self.worker_socket.send(request.SerializeToString())


    def make_request_message(self, data, type, has_next):
        types = {
            "BATCH": RecognitionRequestMessage.BATCH,
            "ONLINE": RecognitionRequestMessage.ONLINE,
        }

        message = RecognitionRequestMessage()
        message.body = data
        message.type = types[type]
        message.has_next = has_next

        return message

    def read_response_from_worker(self):
        response = ResultsMessage()
        response.ParseFromString(self.worker_socket.recv())

        return response

    def format_final_response(self, response):
        return {
            "result": [
                {
                    "alternative": [{"confidence": a.confidence, "transcript": a.transcript} for a in response.alternatives],
                    "final": response.final,
                },
            ],
            "result_index": 0,
        }

    def format_interim_response(self, response):
        return {
            'status': 0,
            'result': {
                'hypotheses': [
                    {'transcript': response.alternatives[0].transcript}
                ]
            },
            'final': False
        }

class Base64Decoder:

    def decode(self, data):
        return base64.b64decode(data)

class NoWorkerAvailableError(Exception):
    pass

class MissingHeaderError(Exception):
    pass
