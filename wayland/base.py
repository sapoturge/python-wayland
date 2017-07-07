import struct


class WaylandObject(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id

    def unpack_event(self, op, data, fds):
        return self, op, data

    def pack_arguments(self, opcode, *args):
        message = b""
        for argument in args:
            if isinstance(argument, WaylandObject):
                argument = argument.obj_id
            if isinstance(argument, int):
                message += struct.pack("i", argument)
            elif isinstance(argument, float):
                message += struct.pack("i", int(argument*256))
            elif isinstance(argument, str):
                message += struct.pack("I", len(argument) + 1)
                message += argument.encode("utf-8")
                message += b"\x00"
                while len(message) % 4 != 0:
                    message += b"\x00"
            elif argument is None:
                message += b"\x00\x00\x00\x00"
        length = (len(message) + 8) << 16
        return struct.pack("II", self.obj_id, length + opcode) + message

    pack_arguments.base = True

    def convert_name(self):
        name = "wl" + self.__class__.__name__
        i = 2
        while i < len(name):
            if name[i].isupper():
                name = name[:i] + "_" + name[i].lower() + name[i+1:]
                i += 1
            i += 1
        return name
