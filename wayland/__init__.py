import os
import socket
import struct
import array
import sys


class Display(object):
    def __init__(self):
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        path = os.path.join(os.getenv("XDG_RUNTIME_DIR"), "wayland-0")
        self.connection.connect(path)
        self.open_ids = []
        self.ids = iter(range(1, 0xffffffff))
        self.obj_id = self.next_id()
        self.objects = {self.obj_id: self}
        self.out_queue = []
        self.event_queue = []
        self.incoming_fds = []
        self.previous_data = ""
        self.registry = self.get_registry()
        self.dispatch()
        self.roundtrip()

    def next_id(self):
        if self.open_ids:
            return self.open_ids.pop(0)
        return next(self.ids)

    def dispatch(self):
        self.flush()
        while not self.event_queue:
            self.recv()
        self.dispatch_pending()

    def dispatch_pending(self):
        while self.event_queue:
            obj, event, args = self.event_queue.pop(0)
            obj.handle_event(event, args)

    def recv(self):
        try:
            fds = array.array("i")
            data, ancdata, msg_flags, address = self.connection.recvmsg(1024, socket.CMSG_SPACE(16 * fds.itemsize))
            for cmsg_level, cmsg_type, cmsg_data in ancdata:
                if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                    fds.fromstring(cmsg_data[:len(cmsg_data) - len(cmsg_data) % fds.itemsize()])
            self.incoming_fds.extend(fds)
            if data:
                self.decode(data)
        except socket.error as e:
            if e.errno == 11:
                return
            raise

    def decode(self, data):
        if self.previous_data:
            data = self.previous_data + data
        while len(data) >= 8:
            obj_id, sizeop = struct.unpack("II", data[:8])
            size = sizeop >> 16
            op = sizeop & 0xFFFF

            if len(data) < size:
                break
            obj = self.objects.get(obj_id, None)
            if obj is not None:
                event = obj.unpack_event(op, data[8:size], self.incoming_fds)
                if event is None:
                    print(obj, op)
                self.event_queue.append(event)
                data = data[size:]
            else:
                print("Error: No Data")
        self.previous_data = data

    def flush(self):
        while self.out_queue:
            print(self.out_queue[0])
            data, fds = self.out_queue.pop(0)
            try:
                sent = self.connection.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])
                while sent < len(data):
                    sent += self.connection.send(data[sent:])
                for fd in fds:
                    os.close(fd)
            except socket.error as e:
                if e.errno == 11:
                    self.out_queue.insert(0, (data, fds))
                    break
                raise

    def roundtrip(self):
        ready = False

        def done():
            nonlocal ready
            ready = True
        l = self.sync()
        l.handle_done = done
        print("Starting to wait")
        while not ready:
            self.dispatch()
        print("Done waiting")

    def sync(self):
        obj_id = self.next_id()
        callback = Callback()
        self.objects[obj_id] = callback
        self.out_queue.append((struct.pack("III", self.obj_id, 12 << 16, obj_id), []))
        return callback

    def get_registry(self):
        obj_id = self.next_id()
        registry = Registry(self, obj_id)
        self.objects[obj_id] = registry
        self.out_queue.append((struct.pack("III", self.obj_id, (12 << 16) + 1, obj_id), []))
        return registry

    def unpack_event(self, op, data, fds):
        if op == 0:
            object_id, code, length = struct.unpack("III", data[:12])
            message = data[12:length+11].decode("utf-8")
            return self, op, (object_id, code, message)
        elif op == 1:
            object_id, = struct.unpack("I", data)
            return self, op, (object_id,)

    def handle_event(self, op, data):
        if op == 0:
            print("Error: Fatal event on object {}: {}".format(data[0], data[2]))
            self.connection.close()
            sys.exit()
        elif op == 1:
            del self.objects[data[0]]

    def disconnect(self):
        self.connection.close()


class Registry(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id
        self.global_objects = {}

    def unpack_event(self, op, data, fds):
        if op == 0:
            object_id, length = struct.unpack("II", data[:8])
            interface = data[8:7+length].decode("utf-8")
            version, = struct.unpack("I", data[-4:])
            return self, op, (object_id, interface, version)
        elif op == 1:
            name = struct.unpack("I", data)
            return self, op, name

    def handle_event(self, op, args):
        if op == 0:
            self.handle_global(*args)
        elif op == 1:
            self.handle_global_remove(*args)

    def handle_global(self, name, interface, version):
        print("Registry event for '{}' (Version {})".format(interface, version))
        if interface in ("wl_compositor", "wl_shell", "wl_shm"):
            obj_id = self.display.next_id()
            self.global_objects[name] = obj_id
            if interface == "wl_compositor":
                self.display.objects[obj_id] = Compositor(self.display, obj_id)
            elif interface == "wl_shell":
                self.display.objects[obj_id] = Shell(self.display, obj_id)
            elif interface == "wl_shm":
                self.display.objects[obj_id] = Shm(self.display, obj_id)
            data = struct.pack("II", name, len(interface)+1)
            data += interface.encode("utf-8")
            data += b"\x00"
            while len(data) % 4 != 0:
                data += b"\x00"
            data += struct.pack("II", version, obj_id)
            self.display.out_queue.append((struct.pack("II", self.obj_id, len(data) + 8 << 16) + data, []))

    def handle_global_remove(self, name):
        if name in self.global_objects:
            obj_id = self.global_objects[name]
            print("{} was removed".format(obj_id))
            if obj_id in self.display.objects:
                del self.display.objects[obj_id]


class Callback(object):
    def unpack_event(self, op, data, fds):
        return self, op, None

    def handle_event(self, op, args):
        self.handle_done()

    def handle_done(self):
        pass


class Compositor(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id

    def create_surface(self):
        obj_id = self.display.next_id()
        self.display.out_queue.append((struct.pack("III", self.obj_id, 12 << 16, obj_id), []))
        surface = Surface(self.display, obj_id)
        self.display.objects[obj_id] = surface
        return surface

    def create_region(self):
        obj_id = self.display.next_id()
        self.display.out_queue.append((struct.pack("III", self.obj_id, (12 << 16) + 1, obj_id), []))
        region = Region(self.display, obj_id)
        self.display.objects[obj_id] = region
        return region


class Surface(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id
        self.buffer = None

    def destroy(self):
        self.display.out_queue.append((struct.pack("II", self.obj_id, 8 << 16), []))

    def attach(self, buffer, x, y):
        self.display.out_queue.append((struct.pack("IIIii", self.obj_id, (20 << 16) + 1, buffer.obj_id, x, y), []))
        self.buffer = buffer

    def set_opaque_region(self, region):
        self.display.out_queue.append((struct.pack("III", self.obj_id, (12 << 16) + 4, region.obj_id), []))

    def set_input_region(self, region):
        self.display.out_queue.append((struct.pack("III", self.obj_id, (12 << 16) + 4, region.obj_id), []))

    def commit(self):
        self.display.out_queue.append((struct.pack("II", self.obj_id, (8 << 16) + 6), []))
        if self.buffer is not None:
            self.buffer.busy = True

    def damage(self, x, y, width, height):
        self.display.out_queue.append((struct.pack("IIiiii", self.obj_id, (24 << 16) + 2, x, y, width, height), []))


class Region(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id

    def destroy(self):
        self.display.out_queue.append((struct.pack("II", self.obj_id, 8 << 16), []))

    def add(self, x, y, width, height):
        self.display.out_queue.append((struct.pack("IIiiii", self.obj_id, (24 << 16) + 1, x, y, width, height), []))

    def remove(self, x, y, width, height):
        self.display.out_queue.append((struct.pack("IIiiii", self.obj_id, (24 << 16) + 2, x, y, width, height), []))


class Shell(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id

    def get_shell_surface(self, surface):
        obj_id = self.display.next_id()
        self.display.out_queue.append((struct.pack("IIII", self.obj_id, 16 << 16, obj_id, surface.obj_id), []))
        shell_surface = ShellSurface(self.display, obj_id)
        self.display.objects[obj_id] = shell_surface
        return shell_surface


class ShellSurface(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id

    def set_toplevel(self):
        self.display.out_queue.append((struct.pack("II", self.obj_id, (8 << 16) + 3), []))

    def unpack_event(self, op, data, fds):
        if op == 0:
            return self, op, data
        elif op == 1:
            pass

    def handle_event(self, op, data):
        if op == 0:
            self.display.out_queue.append((struct.pack("II", self.obj_id, 12 << 16) + data, []))


class Shm(object):
    # wl_shm error values
    INVALID_FORMAT = 0
    INVALID_STRIDE = 1
    INVALID_FD = 2

    # pixel formats
    ARGB8888 = 0
    XRGB8888 = 1
    C8 = 0x20203843
    RGB332 = 0x38424752
    BGR233 = 0x38524742
    XRGB4444 = 0x32315258
    XBGR4444 = 0x32314258
    RGBX4444 = 0x32315852
    BGRX4444 = 0x32315842
    ARGB4444 = 0x32315241
    ABGR4444 = 0x32314241
    RGBA4444 = 0x32314152
    BGRA4444 = 0x32314142
    XRGB1555 = 0x35315258
    XBGR1555 = 0x35314258
    RGBX5551 = 0x35315852
    BGRX5551 = 0x35315842
    ARGB1555 = 0x35315241
    ABGR1555 = 0x35314241
    RGBA5551 = 0x35314152
    BGRA5551 = 0x35314142
    RGB565 = 0x36314752
    BGR565 = 0x36314742
    RGB888 = 0x34324752
    BGR888 = 0x34324742
    XBGR8888 = 0x34324258
    RGBX8888 = 0x34325852
    BGRX8888 = 0x34325842
    ABGR8888 = 0x34324241
    RGBA8888 = 0x34324152
    BGRA8888 = 0x34324142
    XRGB2101010 = 0x30335258
    XBGR2101010 = 0x30334258
    RGBX1010102 = 0x30335852
    BGRX1010102 = 0x30335842
    ARGB2101010 = 0x30335241
    ABGR2101010 = 0x30334241
    RGBA1010102 = 0x30334152
    BGRA1010102 = 0x30334142
    YUYV = 0x56595559
    YVYU = 0x55595659
    UYVY = 0x59565955
    VYUY = 0x59555956
    AYUV = 0x56555941
    NV12 = 0x3231564e
    NV21 = 0x3132564e
    NV16 = 0x3631564e
    NV61 = 0x3136564e
    YUV410 = 0x39565559
    YVU410 = 0x39555659
    YUV411 = 0x31315559
    YVU411 = 0x31315659
    YUV420 = 0x32315559
    YVU420 = 0x32315659
    YUV422 = 0x36315559
    YVU422 = 0x36315659
    YUV444 = 0x34325559
    YVU444 = 0x34325659

    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id
        self.availible = []

    def unpack_event(self, op, data, fds):
        return self, op, struct.unpack("I", data)

    def handle_event(self, op, args):
        self.availible.append(args[0])

    def create_pool(self, fd, size):
        obj_id = self.display.next_id()
        self.display.out_queue.append((struct.pack("IIII", self.obj_id, 16 << 16, obj_id, size), [fd]))
        pool = ShmPool(self.display, obj_id)
        self.display.objects[obj_id] = pool
        return pool


class ShmPool(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id

    def create_buffer(self, offset, width, height, stride, pixel_format):
        obj_id = self.display.next_id()
        self.display.out_queue.append((struct.pack("IIIIIIII", self.obj_id, 32 << 16,
                                                   obj_id, offset, width, height, stride, pixel_format), []))
        buffer = Buffer(self.display, obj_id)
        self.display.objects[obj_id] = buffer
        return buffer


class Buffer(object):
    def __init__(self, display, obj_id):
        self.display = display
        self.obj_id = obj_id
        self.busy = False

    def unpack_event(self, op, data, fds):
        return self, op, None

    def handle_event(self, op, args):
        self.busy = False

