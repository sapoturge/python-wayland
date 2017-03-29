import os
import socket
import array
import struct


class Connection(object):
    def __init__(self):
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        self.connection.setblocking(0)
        path = os.path.join(os.getenv("XDG_RUNTIME_DIR"), "wayland-0")
        self.connection.connect(path)
        self.partial_data = None
        self.incoming_fds = []
        self.objects = {}

    def recv(self):
        data = None
        try:
            fds = array.array("i")
            data, anc_data, msg_flags, address = self.connection.recvmsg(1024, socket.CMSG_SPACE(16*fds.itemsize))
            for cmsg_level, cmsg_type, cmsg_data in anc_data:
                if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                    fds.fromstring(cmsg_data[:len(cmsg_data)-(len(cmsg_data)%fds.itemsize)])
            self.incoming_fds.extend(fds)
            if data:
                self.decode(data)
                return True
        except socket.error as e:
            if e.errno == 11:
                return False
            raise

    def decode(self, data):
        if self.partial_data:
            data = self.partial_data + data
        while len(data) >= 8:
            obj_id, sizeop = struct.unpack("!ii", data[0:8])
            size = sizeop >> 16
            op = sizeop & 0xFFFF
            if len(data) < size:
                break
            obj = self.objects[obj_id]
            if obj:
                obj.handle_event(op, data[8:size])
                data = data[size:]
