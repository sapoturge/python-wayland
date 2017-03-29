"""
    Copyright © 2008-2011 Kristian Høgsberg
    Copyright © 2010-2011 Intel Corporation
    Copyright © 2012-2013 Collabora, Ltd.

    Permission is hereby granted, free of charge, to any person
    obtaining a copy of this software and associated documentation files
    (the "Software"), to deal in the Software without restriction,
    including without limitation the rights to use, copy, modify, merge,
    publish, distribute, sublicense, and/or sell copies of the Software,
    and to permit persons to whom the Software is furnished to do so,
    subject to the following conditions:

    The above copyright notice and this permission notice (including the
    next paragraph) shall be included in all copies or substantial
    portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
    EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
    MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
    NONINFRINGEMENT.  IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
    BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
    ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
    CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
  
"""

import os
import socket
import struct
import array
from .base import WaylandObject


class Display(WaylandObject):
    def __init__(self):
        self.connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM, 0)
        path = os.path.join(os.getenv("XDG_RUNTIME_DIR"), "wayland-0")
        self.connection.connect(path)
        self.connected = True
        self.open_ids = []
        self.ids = iter(range(1, 0xffffffff))
        self.objects = {}
        WaylandObject.__init__(self, self, self.next_id())
        self.out_queue = []
        self.event_queue = []
        self.incoming_fds = []
        self.previous_data = ""
        self.compositor = None
        self.shell = None
        self.shm = None
        self.seat = None
        self.outputs = []
        self.subcompositor = None
        self.data_device_manager = None
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
            method_name = "handle_" + obj.events[event]
            getattr(obj, method_name)(*args)

    def recv(self):
        try:
            fds = array.array("i")
            data, ancdata, msg_flags, address = self.connection.recvmsg(1024, socket.CMSG_SPACE(16 * fds.itemsize))
            for cmsg_level, cmsg_type, cmsg_data in ancdata:
                if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
                    fds.fromstring(cmsg_data[:len(cmsg_data) - len(cmsg_data) % fds.itemsize])
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
            data, fds = self.out_queue.pop(0)
            try:
                sent = self.connection.sendmsg([data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", fds))])
                while sent < len(data):
                    sent += self.connection.send(data[sent:])
                # for fd in fds:
                #     os.close(fd)
            except socket.error as e:
                if e.errno == 11:
                    self.out_queue.insert(0, (data, fds))
                    break
                raise

    def roundtrip(self):
        ready = False

        def done(data):
            nonlocal ready
            ready = True
        l = self.sync()
        l.handle_done = done
        while not ready:
            self.dispatch()

    def unpack_event(self, op, data, fds):
        if op == 0:
            object_id, code, length = struct.unpack("III", data[:12])
            message = data[12:length+11].decode("utf-8")
            return self, op, (object_id, code, message)
        elif op == 1:
            object_id = struct.unpack("I", data)
            return self, op, object_id

    def disconnect(self):
        self.connection.close()

    def sync(self):
        """ asynchronous roundtrip

        The sync request asks the server to emit the 'done' event
        on the returned wl_callback object.  Since requests are
        handled in-order and events are delivered in-order, this can
        be used as a barrier to ensure all previous requests and the
        resulting events have been handled.

        The object returned by this request will be destroyed by the
        compositor after the callback is fired and as such the client must not
        attempt to use it after that point.

        The callback_data passed in the callback is the event serial.

        """
        new_id = self.display.next_id()
        callback = Callback(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(0, new_id), ()))
        return callback

    def get_registry(self):
        """ get global registry object

        This request creates a registry object that allows the client
        to list and bind the global objects available from the
        compositor.

        """
        new_id = self.display.next_id()
        registry = Registry(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(1, new_id), ()))
        return registry

    def handle_error(self, object_id, code, message):
        """ fatal error event
        
        The error event is sent out when a fatal (non-recoverable)
        error has occurred.  The object_id argument is the object
        where the error occurred, most often in response to a request
        to that object.  The code identifies the error and is defined
        by the object interface.  As such, each interface defines its
        own set of error codes.  The message is a brief description
        of the error, for (debugging) convenience.
        
        """
        pass

    # global error values
    INVALID_OBJECT = 0
    INVALID_METHOD = 1
    NO_MEMORY = 2

    def handle_delete_id(self, id):
        """ acknowledge object ID deletion
        
        This event is used internally by the object ID management
        logic.  When a client deletes an object, the server will send
        this event to acknowledge that it has seen the delete request.
        When the client receives this event, it will know that it can
        safely reuse the object ID.
        
        """
        pass

    events = ['error', 'delete_id']
    requests = ['sync', 'get_registry']


class Registry(WaylandObject):

    def __init__(self, display, obj_id):
        WaylandObject.__init__(self, display, obj_id)
        self.global_objects = {}

    def handle_global(self, name, interface, version):
        """ announce global object
        
        Notify the client of global objects.
        
        The event notifies the client that a global object with
        the given name is now available, and it implements the
        given version of the given interface.
        
        """
        if interface in ("wl_compositor", "wl_shell", "wl_shm", "wl_seat", "wl_output", "wl_subcompositor", "wl_data_device_manager"):
            new_id = self.display.next_id()
            self.display.out_queue.append((self.pack_arguments(0, name, interface, version, new_id), ()))
            self.global_objects[name] = new_id
            if interface == "wl_compositor":
                self.display.compositor = Compositor(self.display, new_id)
            elif interface == "wl_shell":
                self.display.shell = Shell(self.display, new_id)
            elif interface == "wl_shm":
                self.display.shm = Shm(self.display, new_id)
            elif interface == "wl_seat":
                self.display.seat = Seat(self.display, new_id)
            elif interface == "wl_output":
                self.display.outputs.append(Output(self.display, new_id))
            elif interface == "wl_subcompositor":
                self.display.subcompositor = Subcompositor(self.display, new_id)
            elif interface == "wl_data_device_manager":
                self.display.data_device_manager = DataDeviceManager(self.display, new_id)
        else:
            print(interface)

    def handle_global_remove(self, name):
        """ announce removal of global object
        
        Notify the client of removed global objects.
        
        This event notifies the client that the global identified
        by name is no longer available.  If the client bound to
        the global using the bind request, the client should now
        destroy that object.
        
        The object remains valid and requests to the object will be
        ignored until the client destroys it, to avoid races between
        the global going away and a client sending a request to it.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        if op == 0:
            object_id, length = struct.unpack("II", data[:8])
            interface = data[8:7+length].decode("utf-8")
            version, = struct.unpack("I", data[-4:])
            return self, op, (object_id, interface, version)
        elif op == 1:
            name = struct.unpack("I", data)
            return self, op, name

    events = ['global', 'global_remove']
    requests = ['bind']


class Callback(WaylandObject):

    def handle_done(self, callback_data):
        """ done event
        
        Notify the client when the related request is done.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        return self, op, struct.unpack("I", data)

    events = ['done']
    requests = []


class Compositor(WaylandObject):

    def create_surface(self):
        """ create new surface
        
        Ask the compositor to create a new surface.
        
        """
        new_id = self.display.next_id()
        surface = Surface(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(0, new_id), ()))
        return surface

    def create_region(self):
        """ create new region
        
        Ask the compositor to create a new region.
        
        """
        new_id = self.display.next_id()
        region = Region(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(1, new_id), ()))
        return region

    events = []
    requests = ['create_surface', 'create_region']


class ShmPool(WaylandObject):

    def create_buffer(self, offset, width, height, stride, format):
        """ create a buffer from the pool
        
        Create a wl_buffer object from the pool.
        
        The buffer is created offset bytes into the pool and has
        width and height as specified.  The stride argument specifies
        the number of bytes from the beginning of one row to the beginning
        of the next.  The format is the pixel format of the buffer and
        must be one of those advertised through the wl_shm.format event.
        
        A buffer will keep a reference to the pool it was created from
        so it is valid to destroy the pool immediately after creating
        a buffer from it.
        
        """
        new_id = self.display.next_id()
        buffer = Buffer(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(0, new_id, offset, width, height, stride, format), ()))
        return buffer

    def destroy(self):
        """ destroy the pool
        
        Destroy the shared memory pool.
        
        The mmapped memory will be released when all
        buffers that have been created from this pool
        are gone.
        
        """
        self.display.out_queue.append((self.pack_arguments(1), ()))

    def resize(self, size):
        """ change the size of the pool mapping
        
        This request will cause the server to remap the backing memory
        for the pool from the file descriptor passed when the pool was
        created, but using the new size.  This request can only be
        used to make the pool bigger.
        
        """
        self.display.out_queue.append((self.pack_arguments(2, size), ()))

    events = []
    requests = ['create_buffer', 'destroy', 'resize']


class Shm(WaylandObject):

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
        WaylandObject.__init__(self, display, obj_id)
        self.availible = []

    def create_pool(self, fd, size):
        """ create a shm pool
        
        Create a new wl_shm_pool object.
        
        The pool can be used to create shared memory based buffer
        objects.  The server will mmap size bytes of the passed file
        descriptor, to use as backing memory for the pool.
        
        """
        new_id = self.display.next_id()
        shm_pool = ShmPool(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(0, new_id, size), (fd,)))
        return shm_pool

    def handle_format(self, format):
        """ pixel format description
        
        Informs the client about a valid pixel format that
        can be used for buffers. Known formats include
        argb8888 and xrgb8888.
        
        """
        self.availible.append(format)

    def unpack_event(self, op, data, fds):
        return self, op, struct.unpack("I", data)

    events = ['format']
    requests = ['create_pool']


class Buffer(WaylandObject):
    def __init__(self, display, obj_id):
        WaylandObject.__init__(self, display, obj_id)
        self.busy = False

    def destroy(self):
        """ destroy a buffer
        
        Destroy a buffer. If and how you need to release the backing
        storage is defined by the buffer factory interface.
        
        For possible side-effects to a surface, see wl_surface.attach.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def handle_release(self):
        """ compositor releases buffer
        
        Sent when this wl_buffer is no longer used by the compositor.
        The client is now free to reuse or destroy this buffer and its
        backing storage.
        
        If a client receives a release event before the frame callback
        requested in the same wl_surface.commit that attaches this
        wl_buffer to a surface, then the client is immediately free to
        reuse the buffer and its backing storage, and does not need a
        second buffer for the next surface content update. Typically
        this is possible, when the compositor maintains a copy of the
        wl_surface contents, e.g. as a GL texture. This is an important
        optimization for GL(ES) compositors with wl_shm clients.
        
        """
        self.busy = False

    events = ['release']
    requests = ['destroy']


class DataOffer(WaylandObject):
    INVALID_FINISH = 0
    INVALID_ACTION_MASK = 1
    INVALID_ACTION = 2
    INVALID_OFFER = 3

    def accept(self, serial, mime_type):
        """ accept one of the offered mime types
        
        Indicate that the client can accept the given mime type, or
        NULL for not accepted.
        
        For objects of version 2 or older, this request is used by the
        client to give feedback whether the client can receive the given
        mime type, or NULL if none is accepted; the feedback does not
        determine whether the drag-and-drop operation succeeds or not.
        
        For objects of version 3 or newer, this request determines the
        final result of the drag-and-drop operation. If the end result
        is that no mime types were accepted, the drag-and-drop operation
        will be cancelled and the corresponding drag source will receive
        wl_data_source.cancelled. Clients may still use this event in
        conjunction with wl_data_source.action for feedback.
        
        """
        self.display.out_queue.append((self.pack_arguments(0, serial, mime_type), ()))

    def receive(self, mime_type, fd):
        """ request that the data is transferred
        
        To transfer the offered data, the client issues this request
        and indicates the mime type it wants to receive.  The transfer
        happens through the passed file descriptor (typically created
        with the pipe system call).  The source client writes the data
        in the mime type representation requested and then closes the
        file descriptor.
        
        The receiving client reads from the read end of the pipe until
        EOF and then closes its end, at which point the transfer is
        complete.
        
        This request may happen multiple times for different mime types,
        both before and after wl_data_device.drop. Drag-and-drop destination
        clients may preemptively fetch data or examine it more closely to
        determine acceptance.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, mime_type), (fd,)))

    def destroy(self):
        """ destroy data offer
        
        Destroy the data offer.
        
        """
        self.display.out_queue.append((self.pack_arguments(2), ()))

    def handle_offer(self, mime_type):
        """ advertise offered mime type
        
        Sent immediately after creating the wl_data_offer object.  One
        event per offered mime type.
        
        """
        pass

    def finish(self):
        """ the offer will no longer be used
        
        Notifies the compositor that the drag destination successfully
        finished the drag-and-drop operation.
        
        Upon receiving this request, the compositor will emit
        wl_data_source.dnd_finished on the drag source client.
        
        It is a client error to perform other requests than
        wl_data_offer.destroy after this one. It is also an error to perform
        this request after a NULL mime type has been set in
        wl_data_offer.accept or no action was received through
        wl_data_offer.action.
        
        """
        self.display.out_queue.append((self.pack_arguments(3), ()))

    def set_actions(self, dnd_actions, preferred_action):
        """ set the available/preferred drag-and-drop actions
        
        Sets the actions that the destination side client supports for
        this operation. This request may trigger the emission of
        wl_data_source.action and wl_data_offer.action events if the compositor
        needs to change the selected action.
        
        This request can be called multiple times throughout the
        drag-and-drop operation, typically in response to wl_data_device.enter
        or wl_data_device.motion events.
        
        This request determines the final result of the drag-and-drop
        operation. If the end result is that no action is accepted,
        the drag source will receive wl_drag_source.cancelled.
        
        The dnd_actions argument must contain only values expressed in the
        wl_data_device_manager.dnd_actions enum, and the preferred_action
        argument must only contain one of those values set, otherwise it
        will result in a protocol error.
        
        While managing an "ask" action, the destination drag-and-drop client
        may perform further wl_data_offer.receive requests, and is expected
        to perform one last wl_data_offer.set_actions request with a preferred
        action other than "ask" (and optionally wl_data_offer.accept) before
        requesting wl_data_offer.finish, in order to convey the action selected
        by the user. If the preferred action is not in the
        wl_data_offer.source_actions mask, an error will be raised.
        
        If the "ask" action is dismissed (e.g. user cancellation), the client
        is expected to perform wl_data_offer.destroy right away.
        
        This request can only be made on drag-and-drop offers, a protocol error
        will be raised otherwise.
        
        """
        self.display.out_queue.append((self.pack_arguments(4, dnd_actions, preferred_action), ()))

    def handle_source_actions(self, source_actions):
        """ notify the source-side available actions
        
        This event indicates the actions offered by the data source. It
        will be sent right after wl_data_device.enter, or anytime the source
        side changes its offered actions through wl_data_source.set_actions.
        
        """
        pass

    def handle_action(self, dnd_action):
        """ notify the selected action
        
        This event indicates the action selected by the compositor after
        matching the source/destination side actions. Only one action (or
        none) will be offered here.
        
        This event can be emitted multiple times during the drag-and-drop
        operation in response to destination side action changes through
        wl_data_offer.set_actions.
        
        This event will no longer be emitted after wl_data_device.drop
        happened on the drag-and-drop destination, the client must
        honor the last action received, or the last preferred one set
        through wl_data_offer.set_actions when handling an "ask" action.
        
        Compositors may also change the selected action on the fly, mainly
        in response to keyboard modifier changes during the drag-and-drop
        operation.
        
        The most recent action received is always the valid one. Prior to
        receiving wl_data_device.drop, the chosen action may change (e.g.
        due to keyboard modifiers being pressed). At the time of receiving
        wl_data_device.drop the drag-and-drop destination must honor the
        last action received.
        
        Action changes may still happen after wl_data_device.drop,
        especially on "ask" actions, where the drag-and-drop destination
        may choose another action afterwards. Action changes happening
        at this stage are always the result of inter-client negotiation, the
        compositor shall no longer be able to induce a different action.
        
        Upon "ask" actions, it is expected that the drag-and-drop destination
        may potentially choose a different action and/or mime type,
        based on wl_data_offer.source_actions and finally chosen by the
        user (e.g. popping up a menu with the available options). The
        final wl_data_offer.set_actions and wl_data_offer.accept requests
        must happen before the call to wl_data_offer.finish.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        if op == 0:
            length = struct.unpack("I", data[:4])[0]
            mime = data[4:4+length].decode("utf-8")
            return self, op, (mime,)
        elif op == 1 or op == 2:
            return self, op, struct.unpack("I", data)

    events = ['offer', 'source_actions', 'action']
    requests = ['accept', 'receive', 'destroy', 'finish', 'set_actions']


class DataSource(WaylandObject):
    INVALID_ACTION_MASK = 0
    INVALID_SOURCE = 1

    def offer(self, mime_type):
        """ add an offered mime type
        
        This request adds a mime type to the set of mime types
        advertised to targets.  Can be called several times to offer
        multiple types.
        
        """
        self.display.out_queue.append((self.pack_arguments(0, mime_type), ()))

    def destroy(self):
        """ destroy the data source
        
        Destroy the data source.
        
        """
        self.display.out_queue.append((self.pack_arguments(1), ()))

    def handle_target(self, mime_type):
        """ a target accepts an offered mime type
        
        Sent when a target accepts pointer_focus or motion events.  If
        a target does not accept any of the offered types, type is NULL.
        
        Used for feedback during drag-and-drop.
        
        """
        pass

    def handle_send(self, mime_type, fd):
        """ send the data
        
        Request for data from the client.  Send the data as the
        specified mime type over the passed file descriptor, then
        close it.
        
        """
        pass

    def handle_cancelled(self):
        """ selection was cancelled
        
        This data source is no longer valid. There are several reasons why
        this could happen:
        
        - The data source has been replaced by another data source.
        - The drag-and-drop operation was performed, but the drop destination
        did not accept any of the mime types offered through
        wl_data_source.target.
        - The drag-and-drop operation was performed, but the drop destination
        did not select any of the actions present in the mask offered through
        wl_data_source.action.
        - The drag-and-drop operation was performed but didn't happen over a
        surface.
        - The compositor cancelled the drag-and-drop operation (e.g. compositor
        dependent timeouts to avoid stale drag-and-drop transfers).
        
        The client should clean up and destroy this data source.
        
        For objects of version 2 or older, wl_data_source.cancelled will
        only be emitted if the data source was replaced by another data
        source.
        
        """
        pass

    def set_actions(self, dnd_actions):
        """ set the available drag-and-drop actions
        
        Sets the actions that the source side client supports for this
        operation. This request may trigger wl_data_source.action and
        wl_data_offer.action events if the compositor needs to change the
        selected action.
        
        The dnd_actions argument must contain only values expressed in the
        wl_data_device_manager.dnd_actions enum, otherwise it will result
        in a protocol error.
        
        This request must be made once only, and can only be made on sources
        used in drag-and-drop, so it must be performed before
        wl_data_device.start_drag. Attempting to use the source other than
        for drag-and-drop will raise a protocol error.
        
        """
        self.display.out_queue.append((self.pack_arguments(2, dnd_actions), ()))

    def handle_dnd_drop_performed(self):
        """ the drag-and-drop operation physically finished
        
        The user performed the drop action. This event does not indicate
        acceptance, wl_data_source.cancelled may still be emitted afterwards
        if the drop destination does not accept any mime type.
        
        However, this event might however not be received if the compositor
        cancelled the drag-and-drop operation before this event could happen.
        
        Note that the data_source may still be used in the future and should
        not be destroyed here.
        
        """
        pass

    def handle_dnd_finished(self):
        """ the drag-and-drop operation concluded
        
        The drop destination finished interoperating with this data
        source, so the client is now free to destroy this data source and
        free all associated data.
        
        If the action used to perform the operation was "move", the
        source can now delete the transferred data.
        
        """
        pass

    def handle_action(self, dnd_action):
        """ notify the selected action
        
        This event indicates the action selected by the compositor after
        matching the source/destination side actions. Only one action (or
        none) will be offered here.
        
        This event can be emitted multiple times during the drag-and-drop
        operation, mainly in response to destination side changes through
        wl_data_offer.set_actions, and as the data device enters/leaves
        surfaces.
        
        It is only possible to receive this event after
        wl_data_source.dnd_drop_performed if the drag-and-drop operation
        ended in an "ask" action, in which case the final wl_data_source.action
        event will happen immediately before wl_data_source.dnd_finished.
        
        Compositors may also change the selected action on the fly, mainly
        in response to keyboard modifier changes during the drag-and-drop
        operation.
        
        The most recent action received is always the valid one. The chosen
        action may change alongside negotiation (e.g. an "ask" action can turn
        into a "move" operation), so the effects of the final action must
        always be applied in wl_data_offer.dnd_finished.
        
        Clients can trigger cursor surface changes from this point, so
        they reflect the current action.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        if op == 0:
            length = struct.unpack("I", data[:4])[0]
            mime = data[4:length].decode("utf-8")
            return self, op, (mime,)
        elif op == 1:
            length = struct.unpack("I", data[:4])[0]
            mime = data[4:length].decode("utf-8")
            return self, op, (mime, fds.pop(0))
        elif op == 2:
            return self, op, ()
        elif op == 3:
            return self, op, ()
        elif op == 4:
            return self, op, ()
        elif op == 5:
            return self, op, struct.unpack("I", data)

    events = ['target', 'send', 'cancelled', 'dnd_drop_performed', 'dnd_finished', 'action']
    requests = ['offer', 'destroy', 'set_actions']


class DataDevice(WaylandObject):
    ROLE = 0

    def start_drag(self, source, origin, icon, serial):
        """ start drag-and-drop operation
        
        This request asks the compositor to start a drag-and-drop
        operation on behalf of the client.
        
        The source argument is the data source that provides the data
        for the eventual data transfer. If source is NULL, enter, leave
        and motion events are sent only to the client that initiated the
        drag and the client is expected to handle the data passing
        internally.
        
        The origin surface is the surface where the drag originates and
        the client must have an active implicit grab that matches the
        serial.
        
        The icon surface is an optional (can be NULL) surface that
        provides an icon to be moved around with the cursor.  Initially,
        the top-left corner of the icon surface is placed at the cursor
        hotspot, but subsequent wl_surface.attach request can move the
        relative position. Attach requests must be confirmed with
        wl_surface.commit as usual. The icon surface is given the role of
        a drag-and-drop icon. If the icon surface already has another role,
        it raises a protocol error.
        
        The current and pending input regions of the icon wl_surface are
        cleared, and wl_surface.set_input_region is ignored until the
        wl_surface is no longer used as the icon surface. When the use
        as an icon ends, the current and pending input regions become
        undefined, and the wl_surface is unmapped.
        
        """
        self.display.out_queue.append((self.pack_arguments(0, source, origin, icon, serial), ()))

    def set_selection(self, source, serial):
        """ copy data to the selection
        
        This request asks the compositor to set the selection
        to the data from the source on behalf of the client.
        
        To unset the selection, set the source to NULL.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, source, serial), ()))

    def handle_data_offer(self, offer):
        """ introduce a new wl_data_offer
        
        The data_offer event introduces a new wl_data_offer object,
        which will subsequently be used in either the
        data_device.enter event (for drag-and-drop) or the
        data_device.selection event (for selections).  Immediately
        following the data_device_data_offer event, the new data_offer
        object will send out data_offer.offer events to describe the
        mime types it offers.
        
        """
        pass

    def handle_enter(self, serial, surface, x, y, offer):
        """ initiate drag-and-drop session
        
        This event is sent when an active drag-and-drop pointer enters
        a surface owned by the client.  The position of the pointer at
        enter time is provided by the x and y arguments, in surface-local
        coordinates.
        
        """
        pass

    def handle_leave(self):
        """ end drag-and-drop session
        
        This event is sent when the drag-and-drop pointer leaves the
        surface and the session ends.  The client must destroy the
        wl_data_offer introduced at enter time at this point.
        
        """
        pass

    def handle_motion(self, time, x, y):
        """ drag-and-drop session motion
        
        This event is sent when the drag-and-drop pointer moves within
        the currently focused surface. The new position of the pointer
        is provided by the x and y arguments, in surface-local
        coordinates.
        
        """
        pass

    def handle_drop(self):
        """ end drag-and-drop session successfully
        
        The event is sent when a drag-and-drop operation is ended
        because the implicit grab is removed.
        
        The drag-and-drop destination is expected to honor the last action
        received through wl_data_offer.action, if the resulting action is
        "copy" or "move", the destination can still perform
        wl_data_offer.receive requests, and is expected to end all
        transfers with a wl_data_offer.finish request.
        
        If the resulting action is "ask", the action will not be considered
        final. The drag-and-drop destination is expected to perform one last
        wl_data_offer.set_actions request, or wl_data_offer.destroy in order
        to cancel the operation.
        
        """
        pass

    def handle_selection(self, id):
        """ advertise new selection
        
        The selection event is sent out to notify the client of a new
        wl_data_offer for the selection for this device.  The
        data_device.data_offer and the data_offer.offer events are
        sent out immediately before this event to introduce the data
        offer object.  The selection event is sent to a client
        immediately before receiving keyboard focus and when a new
        selection is set while the client has keyboard focus.  The
        data_offer is valid until a new data_offer or NULL is received
        or until the client loses keyboard focus.  The client must
        destroy the previous selection data_offer, if any, upon receiving
        this event.
        
        """
        pass

    def release(self):
        """ destroy data device
        
        This request destroys the data device.
        
        """
        self.display.out_queue.append((self.pack_arguments(2), ()))

    def unpack_event(self, op, data, fds):
        if op == 0:
            return self, op, (DataOffer(self.display, struct.unpack("I", data)[0]),)
        elif op == 1:
            serial, s, x, y, o = struct.unpack("IIIII", data)
            surface = self.display.objects[s]
            offer = self.display.objects[o]
            return self, op, (serial, surface, x/256, y/256, offer)
        elif op == 2:
            return self, op, ()
        elif op == 3:
            t, x, y = struct.unpack("III", data)
            return self, op, (t, x/256, y/256)
        elif op == 4:
            return self, op, ()
        elif op == 5:
            offer = struct.unpack("I", data)[0]
            return self, op, (self.display.objects[offer])

    events = ['data_offer', 'enter', 'leave', 'motion', 'drop', 'selection']
    requests = ['start_drag', 'set_selection', 'release']


class DataDeviceManager(WaylandObject):

    def create_data_source(self):
        """ create a new data source
        
        Create a new data source.
        
        """
        new_id = self.display.next_id()
        data_source = DataSource(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(0, new_id), ()))
        return data_source

    def get_data_device(self, seat):
        """ create a new data device
        
        Create a new data device for a given seat.
        
        """
        new_id = self.display.next_id()
        data_device = DataDevice(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(1, new_id, seat), ()))
        return data_device

    # drag and drop actions
    NONE = 0
    COPY = 1
    MOVE = 2
    ASK = 4

    events = []
    requests = ['create_data_source', 'get_data_device']


class Shell(WaylandObject):
    ROLE = 0

    def get_shell_surface(self, surface):
        """ create a shell surface from a surface
        
        Create a shell surface for an existing surface. This gives
        the wl_surface the role of a shell surface. If the wl_surface
        already has another role, it raises a protocol error.
        
        Only one shell surface can be associated with a given surface.
        
        """
        new_id = self.display.next_id()
        shell_surface = ShellSurface(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(0, new_id, surface), ()))
        return shell_surface

    events = []
    requests = ['get_shell_surface']


class ShellSurface(WaylandObject):

    def pong(self, serial):
        """ respond to a ping event
        
        A client must respond to a ping event with a pong request or
        the client may be deemed unresponsive.
        
        """
        self.display.out_queue.append((self.pack_arguments(0, serial), ()))

    def move(self, seat, serial):
        """ start an interactive move
        
        Start a pointer-driven move of the surface.
        
        This request must be used in response to a button press event.
        The server may ignore move requests depending on the state of
        the surface (e.g. fullscreen or maximized).
        
        """
        self.display.out_queue.append((self.pack_arguments(1, seat, serial), ()))

    # edge values for resizing
    NONE = 0
    TOP = 1
    BOTTOM = 2
    LEFT = 4
    TOP_LEFT = 5
    BOTTOM_LEFT = 6
    RIGHT = 8
    TOP_RIGHT = 9
    BOTTOM_RIGHT = 10

    def resize(self, seat, serial, edges):
        """ start an interactive resize
        
        Start a pointer-driven resizing of the surface.
        
        This request must be used in response to a button press event.
        The server may ignore resize requests depending on the state of
        the surface (e.g. fullscreen or maximized).
        
        """
        self.display.out_queue.append((self.pack_arguments(2, seat, serial, edges), ()))

    def set_toplevel(self):
        """ make the surface a toplevel surface
        
        Map the surface as a toplevel surface.
        
        A toplevel surface is not fullscreen, maximized or transient.
        
        """
        self.display.out_queue.append((self.pack_arguments(3), ()))

    # details of transient behaviour
    INACTIVE = 0x1

    def set_transient(self, parent, x, y, flags):
        """ make the surface a transient surface
        
        Map the surface relative to an existing surface.
        
        The x and y arguments specify the location of the upper left
        corner of the surface relative to the upper left corner of the
        parent surface, in surface-local coordinates.
        
        The flags argument controls details of the transient behaviour.
        
        """
        self.display.out_queue.append((self.pack_arguments(4, parent, x, y, flags), ()))

    # different method to set the surface fullscreen
    DEFAULT = 0
    SCALE = 1
    DRIVER = 2
    FILL = 3

    def set_fullscreen(self, method, framerate, output):
        """ make the surface a fullscreen surface
        
        Map the surface as a fullscreen surface.
        
        If an output parameter is given then the surface will be made
        fullscreen on that output. If the client does not specify the
        output then the compositor will apply its policy - usually
        choosing the output on which the surface has the biggest surface
        area.
        
        The client may specify a method to resolve a size conflict
        between the output size and the surface size - this is provided
        through the method parameter.
        
        The framerate parameter is used only when the method is set
        to "driver", to indicate the preferred framerate. A value of 0
        indicates that the client does not care about framerate.  The
        framerate is specified in mHz, that is framerate of 60000 is 60Hz.
        
        A method of "scale" or "driver" implies a scaling operation of
        the surface, either via a direct scaling operation or a change of
        the output mode. This will override any kind of output scaling, so
        that mapping a surface with a buffer size equal to the mode can
        fill the screen independent of buffer_scale.
        
        A method of "fill" means we don't scale up the buffer, however
        any output scale is applied. This means that you may run into
        an edge case where the application maps a buffer with the same
        size of the output mode but buffer_scale 1 (thus making a
        surface larger than the output). In this case it is allowed to
        downscale the results to fit the screen.
        
        The compositor must reply to this request with a configure event
        with the dimensions for the output on which the surface will
        be made fullscreen.
        
        """
        self.display.out_queue.append((self.pack_arguments(5, method, framerate, output), ()))

    def set_popup(self, seat, serial, parent, x, y, flags):
        """ make the surface a popup surface
        
        Map the surface as a popup.
        
        A popup surface is a transient surface with an added pointer
        grab.
        
        An existing implicit grab will be changed to owner-events mode,
        and the popup grab will continue after the implicit grab ends
        (i.e. releasing the mouse button does not cause the popup to
        be unmapped).
        
        The popup grab continues until the window is destroyed or a
        mouse button is pressed in any other client's window. A click
        in any of the client's surfaces is reported as normal, however,
        clicks in other clients' surfaces will be discarded and trigger
        the callback.
        
        The x and y arguments specify the location of the upper left
        corner of the surface relative to the upper left corner of the
        parent surface, in surface-local coordinates.
        
        """
        self.display.out_queue.append((self.pack_arguments(6, seat, serial, parent, x, y, flags), ()))

    def set_maximized(self, output):
        """ make the surface a maximized surface
        
        Map the surface as a maximized surface.
        
        If an output parameter is given then the surface will be
        maximized on that output. If the client does not specify the
        output then the compositor will apply its policy - usually
        choosing the output on which the surface has the biggest surface
        area.
        
        The compositor will reply with a configure event telling
        the expected new surface size. The operation is completed
        on the next buffer attach to this surface.
        
        A maximized surface typically fills the entire output it is
        bound to, except for desktop elements such as panels. This is
        the main difference between a maximized shell surface and a
        fullscreen shell surface.
        
        The details depend on the compositor implementation.
        
        """
        self.display.out_queue.append((self.pack_arguments(7, output), ()))

    def set_title(self, title):
        """ set surface title
        
        Set a short title for the surface.
        
        This string may be used to identify the surface in a task bar,
        window list, or other user interface elements provided by the
        compositor.
        
        The string must be encoded in UTF-8.
        
        """
        self.display.out_queue.append((self.pack_arguments(8, title), ()))

    def set_class(self, class_):
        """ set surface class
        
        Set a class for the surface.
        
        The surface class identifies the general class of applications
        to which the surface belongs. A common convention is to use the
        file name (or the full path if it is a non-standard location) of
        the application's .desktop file as the class.
        
        """
        self.display.out_queue.append((self.pack_arguments(9, class_), ()))

    def handle_ping(self, serial):
        """ ping client
        
        Ping a client to check if it is receiving events and sending
        requests. A client is expected to reply with a pong request.
        
        """
        self.pong(serial)

    def handle_configure(self, edges, width, height):
        """ suggest resize
        
        The configure event asks the client to resize its surface.
        
        The size is a hint, in the sense that the client is free to
        ignore it if it doesn't resize, pick a smaller size (to
        satisfy aspect ratio or resize in steps of NxM pixels).
        
        The edges parameter provides a hint about how the surface
        was resized. The client may use this information to decide
        how to adjust its content to the new size (e.g. a scrolling
        area might adjust its content position to leave the viewable
        content unmoved).
        
        The client is free to dismiss all but the last configure
        event it received.
        
        The width and height arguments specify the size of the window
        in surface-local coordinates.
        
        """
        pass

    def handle_popup_done(self):
        """ popup interaction is done
        
        The popup_done event is sent out when a popup grab is broken,
        that is, when the user clicks a surface that doesn't belong
        to the client owning the popup surface.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        if op == 0:
            return self, op, struct.unpack("I", data)
        elif op == 1:
            return self, op, struct.unpack("Iii", data)
        elif op == 2:
            return self, op, ()

    events = ['ping', 'configure', 'popup_done']
    requests = ['pong', 'move', 'resize', 'set_toplevel', 'set_transient', 'set_fullscreen', 'set_popup', 'set_maximized', 'set_title', 'set_class']


class Surface(WaylandObject):
    def __init__(self, display, obj_id):
        WaylandObject.__init__(self, display, obj_id)
        self.buffer = None

    # wl_surface error values
    INVALID_SCALE = 0
    INVALID_TRANSFORM = 1

    def destroy(self):
        """ delete surface
        
        Deletes the surface and invalidates its object ID.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def attach(self, buffer, x, y):
        """ set the surface contents
        
        Set a buffer as the content of this surface.
        
        The new size of the surface is calculated based on the buffer
        size transformed by the inverse buffer_transform and the
        inverse buffer_scale. This means that the supplied buffer
        must be an integer multiple of the buffer_scale.
        
        The x and y arguments specify the location of the new pending
        buffer's upper left corner, relative to the current buffer's upper
        left corner, in surface-local coordinates. In other words, the
        x and y, combined with the new surface size define in which
        directions the surface's size changes.
        
        Surface contents are double-buffered state, see wl_surface.commit.
        
        The initial surface contents are void; there is no content.
        wl_surface.attach assigns the given wl_buffer as the pending
        wl_buffer. wl_surface.commit makes the pending wl_buffer the new
        surface contents, and the size of the surface becomes the size
        calculated from the wl_buffer, as described above. After commit,
        there is no pending buffer until the next attach.
        
        Committing a pending wl_buffer allows the compositor to read the
        pixels in the wl_buffer. The compositor may access the pixels at
        any time after the wl_surface.commit request. When the compositor
        will not access the pixels anymore, it will send the
        wl_buffer.release event. Only after receiving wl_buffer.release,
        the client may reuse the wl_buffer. A wl_buffer that has been
        attached and then replaced by another attach instead of committed
        will not receive a release event, and is not used by the
        compositor.
        
        Destroying the wl_buffer after wl_buffer.release does not change
        the surface contents. However, if the client destroys the
        wl_buffer before receiving the wl_buffer.release event, the surface
        contents become undefined immediately.
        
        If wl_surface.attach is sent with a NULL wl_buffer, the
        following wl_surface.commit will remove the surface content.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, buffer, x, y), ()))
        self.buffer = buffer

    def damage(self, x, y, width, height):
        """ mark part of the surface damaged
        
        This request is used to describe the regions where the pending
        buffer is different from the current surface contents, and where
        the surface therefore needs to be repainted. The compositor
        ignores the parts of the damage that fall outside of the surface.
        
        Damage is double-buffered state, see wl_surface.commit.
        
        The damage rectangle is specified in surface-local coordinates,
        where x and y specify the upper left corner of the damage rectangle.
        
        The initial value for pending damage is empty: no damage.
        wl_surface.damage adds pending damage: the new pending damage
        is the union of old pending damage and the given rectangle.
        
        wl_surface.commit assigns pending damage as the current damage,
        and clears pending damage. The server will clear the current
        damage as it repaints the surface.
        
        Alternatively, damage can be posted with wl_surface.damage_buffer
        which uses buffer coordinates instead of surface coordinates,
        and is probably the preferred and intuitive way of doing this.
        
        """
        self.display.out_queue.append((self.pack_arguments(2, x, y, width, height), ()))

    def frame(self):
        """ request a frame throttling hint
        
        Request a notification when it is a good time to start drawing a new
        frame, by creating a frame callback. This is useful for throttling
        redrawing operations, and driving animations.
        
        When a client is animating on a wl_surface, it can use the 'frame'
        request to get notified when it is a good time to draw and commit the
        next frame of animation. If the client commits an update earlier than
        that, it is likely that some updates will not make it to the display,
        and the client is wasting resources by drawing too often.
        
        The frame request will take effect on the next wl_surface.commit.
        The notification will only be posted for one frame unless
        requested again. For a wl_surface, the notifications are posted in
        the order the frame requests were committed.
        
        The server must send the notifications so that a client
        will not send excessive updates, while still allowing
        the highest possible update rate for clients that wait for the reply
        before drawing again. The server should give some time for the client
        to draw and commit after sending the frame callback events to let it
        hit the next output refresh.
        
        A server should avoid signaling the frame callbacks if the
        surface is not visible in any way, e.g. the surface is off-screen,
        or completely obscured by other opaque surfaces.
        
        The object returned by this request will be destroyed by the
        compositor after the callback is fired and as such the client must not
        attempt to use it after that point.
        
        The callback_data passed in the callback is the current time, in
        milliseconds, with an undefined base.
        
        """
        new_id = self.display.next_id()
        callback = Callback(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(3, new_id), ()))
        return callback

    def set_opaque_region(self, region):
        """ set opaque region
        
        This request sets the region of the surface that contains
        opaque content.
        
        The opaque region is an optimization hint for the compositor
        that lets it optimize the redrawing of content behind opaque
        regions.  Setting an opaque region is not required for correct
        behaviour, but marking transparent content as opaque will result
        in repaint artifacts.
        
        The opaque region is specified in surface-local coordinates.
        
        The compositor ignores the parts of the opaque region that fall
        outside of the surface.
        
        Opaque region is double-buffered state, see wl_surface.commit.
        
        wl_surface.set_opaque_region changes the pending opaque region.
        wl_surface.commit copies the pending region to the current region.
        Otherwise, the pending and current regions are never changed.
        
        The initial value for an opaque region is empty. Setting the pending
        opaque region has copy semantics, and the wl_region object can be
        destroyed immediately. A NULL wl_region causes the pending opaque
        region to be set to empty.
        
        """
        self.display.out_queue.append((self.pack_arguments(4, region), ()))

    def set_input_region(self, region):
        """ set input region
        
        This request sets the region of the surface that can receive
        pointer and touch events.
        
        Input events happening outside of this region will try the next
        surface in the server surface stack. The compositor ignores the
        parts of the input region that fall outside of the surface.
        
        The input region is specified in surface-local coordinates.
        
        Input region is double-buffered state, see wl_surface.commit.
        
        wl_surface.set_input_region changes the pending input region.
        wl_surface.commit copies the pending region to the current region.
        Otherwise the pending and current regions are never changed,
        except cursor and icon surfaces are special cases, see
        wl_pointer.set_cursor and wl_data_device.start_drag.
        
        The initial value for an input region is infinite. That means the
        whole surface will accept input. Setting the pending input region
        has copy semantics, and the wl_region object can be destroyed
        immediately. A NULL wl_region causes the input region to be set
        to infinite.
        
        """
        self.display.out_queue.append((self.pack_arguments(5, region), ()))

    def commit(self):
        """ commit pending surface state
        
        Surface state (input, opaque, and damage regions, attached buffers,
        etc.) is double-buffered. Protocol requests modify the pending state,
        as opposed to the current state in use by the compositor. A commit
        request atomically applies all pending state, replacing the current
        state. After commit, the new pending state is as documented for each
        related request.
        
        On commit, a pending wl_buffer is applied first, and all other state
        second. This means that all coordinates in double-buffered state are
        relative to the new wl_buffer coming into use, except for
        wl_surface.attach itself. If there is no pending wl_buffer, the
        coordinates are relative to the current surface contents.
        
        All requests that need a commit to become effective are documented
        to affect double-buffered state.
        
        Other interfaces may add further double-buffered surface state.
        
        """
        self.display.out_queue.append((self.pack_arguments(6), ()))

    def handle_enter(self, output):
        """ surface enters an output
        
        This is emitted whenever a surface's creation, movement, or resizing
        results in some part of it being within the scanout region of an
        output.
        
        Note that a surface may be overlapping with zero or more outputs.
        
        """
        pass

    def handle_leave(self, output):
        """ surface leaves an output
        
        This is emitted whenever a surface's creation, movement, or resizing
        results in it no longer having any part of it within the scanout region
        of an output.
        
        """
        pass

    def set_buffer_transform(self, transform):
        """ sets the buffer transformation
        
        This request sets an optional transformation on how the compositor
        interprets the contents of the buffer attached to the surface. The
        accepted values for the transform parameter are the values for
        wl_output.transform.
        
        Buffer transform is double-buffered state, see wl_surface.commit.
        
        A newly created surface has its buffer transformation set to normal.
        
        wl_surface.set_buffer_transform changes the pending buffer
        transformation. wl_surface.commit copies the pending buffer
        transformation to the current one. Otherwise, the pending and current
        values are never changed.
        
        The purpose of this request is to allow clients to render content
        according to the output transform, thus permitting the compositor to
        use certain optimizations even if the display is rotated. Using
        hardware overlays and scanning out a client buffer for fullscreen
        surfaces are examples of such optimizations. Those optimizations are
        highly dependent on the compositor implementation, so the use of this
        request should be considered on a case-by-case basis.
        
        Note that if the transform value includes 90 or 270 degree rotation,
        the width of the buffer will become the surface height and the height
        of the buffer will become the surface width.
        
        If transform is not one of the values from the
        wl_output.transform enum the invalid_transform protocol error
        is raised.
        
        """
        self.display.out_queue.append((self.pack_arguments(7, transform), ()))

    def set_buffer_scale(self, scale):
        """ sets the buffer scaling factor
        
        This request sets an optional scaling factor on how the compositor
        interprets the contents of the buffer attached to the window.
        
        Buffer scale is double-buffered state, see wl_surface.commit.
        
        A newly created surface has its buffer scale set to 1.
        
        wl_surface.set_buffer_scale changes the pending buffer scale.
        wl_surface.commit copies the pending buffer scale to the current one.
        Otherwise, the pending and current values are never changed.
        
        The purpose of this request is to allow clients to supply higher
        resolution buffer data for use on high resolution outputs. It is
        intended that you pick the same buffer scale as the scale of the
        output that the surface is displayed on. This means the compositor
        can avoid scaling when rendering the surface on that output.
        
        Note that if the scale is larger than 1, then you have to attach
        a buffer that is larger (by a factor of scale in each dimension)
        than the desired surface size.
        
        If scale is not positive the invalid_scale protocol error is
        raised.
        
        """
        self.display.out_queue.append((self.pack_arguments(8, scale), ()))

    def damage_buffer(self, x, y, width, height):
        """ mark part of the surface damaged using buffer coordinates
        
        This request is used to describe the regions where the pending
        buffer is different from the current surface contents, and where
        the surface therefore needs to be repainted. The compositor
        ignores the parts of the damage that fall outside of the surface.
        
        Damage is double-buffered state, see wl_surface.commit.
        
        The damage rectangle is specified in buffer coordinates,
        where x and y specify the upper left corner of the damage rectangle.
        
        The initial value for pending damage is empty: no damage.
        wl_surface.damage_buffer adds pending damage: the new pending
        damage is the union of old pending damage and the given rectangle.
        
        wl_surface.commit assigns pending damage as the current damage,
        and clears pending damage. The server will clear the current
        damage as it repaints the surface.
        
        This request differs from wl_surface.damage in only one way - it
        takes damage in buffer coordinates instead of surface-local
        coordinates. While this generally is more intuitive than surface
        coordinates, it is especially desirable when using wp_viewport
        or when a drawing library (like EGL) is unaware of buffer scale
        and buffer transform.
        
        Note: Because buffer transformation changes and damage requests may
        be interleaved in the protocol stream, it is impossible to determine
        the actual mapping between surface and buffer damage until
        wl_surface.commit time. Therefore, compositors wishing to take both
        kinds of damage into account will have to accumulate damage from the
        two requests separately and only transform from one to the other
        after receiving the wl_surface.commit.
        
        """
        self.display.out_queue.append((self.pack_arguments(9, x, y, width, height), ()))

    def unpack_event(self, op, data, fds):
        return self, op, (self.display.objects[struct.unpack("I", data)[0]],)

    events = ['enter', 'leave']
    requests = ['destroy', 'attach', 'damage', 'frame', 'set_opaque_region', 'set_input_region', 'commit', 'set_buffer_transform', 'set_buffer_scale', 'damage_buffer']


class Seat(WaylandObject):

    # seat capability bitmask
    POINTER = 1
    KEYBOARD = 2
    TOUCH = 4

    def __init__(self, display, obj_id):
        WaylandObject.__init__(self, display, obj_id)
        self.pointer = None
        self.keyboard = None
        self.touch = None

    def handle_capabilities(self, capabilities):
        """ seat capabilities changed
        
        This is emitted whenever a seat gains or loses the pointer,
        keyboard or touch capabilities.  The argument is a capability
        enum containing the complete set of capabilities this seat has.
        
        When the pointer capability is added, a client may create a
        wl_pointer object using the wl_seat.get_pointer request. This object
        will receive pointer events until the capability is removed in the
        future.
        
        When the pointer capability is removed, a client should destroy the
        wl_pointer objects associated with the seat where the capability was
        removed, using the wl_pointer.release request. No further pointer
        events will be received on these objects.
        
        In some compositors, if a seat regains the pointer capability and a
        client has a previously obtained wl_pointer object of version 4 or
        less, that object may start sending pointer events again. This
        behavior is considered a misinterpretation of the intended behavior
        and must not be relied upon by the client. wl_pointer objects of
        version 5 or later must not send events if created before the most
        recent event notifying the client of an added pointer capability.
        
        The above behavior also applies to wl_keyboard and wl_touch with the
        keyboard and touch capabilities, respectively.
        
        """
        if capabilities & self.TOUCH:
            self.touch = self.touch or self.get_touch()
        elif self.touch is not None:
            self.touch.release()
            self.touch = None
        if capabilities & self.KEYBOARD:
            self.keyboard = self.keyboard or self.get_keyboard()
        elif self.keyboard is not None:
            self.keyboard.release()
            self.keyboard = None
        if capabilities & self.POINTER:
            self.pointer = self.pointer or self.get_pointer()
        elif self.pointer is not None:
            self.pointer.release()
            self.pointer = None

    def get_pointer(self):
        """ return pointer object
        
        The ID provided will be initialized to the wl_pointer interface
        for this seat.
        
        This request only takes effect if the seat has the pointer
        capability, or has had the pointer capability in the past.
        It is a protocol violation to issue this request on a seat that has
        never had the pointer capability.
        
        """
        new_id = self.display.next_id()
        pointer = Pointer(self.display, new_id, self)
        self.display.out_queue.append((self.pack_arguments(0, new_id), ()))
        return pointer

    def get_keyboard(self):
        """ return keyboard object
        
        The ID provided will be initialized to the wl_keyboard interface
        for this seat.
        
        This request only takes effect if the seat has the keyboard
        capability, or has had the keyboard capability in the past.
        It is a protocol violation to issue this request on a seat that has
        never had the keyboard capability.
        
        """
        new_id = self.display.next_id()
        keyboard = Keyboard(self.display, new_id, self)
        self.display.out_queue.append((self.pack_arguments(1, new_id), ()))
        return keyboard

    def get_touch(self):
        """ return touch object
        
        The ID provided will be initialized to the wl_touch interface
        for this seat.
        
        This request only takes effect if the seat has the touch
        capability, or has had the touch capability in the past.
        It is a protocol violation to issue this request on a seat that has
        never had the touch capability.
        
        """
        new_id = self.display.next_id()
        touch = Touch(self.display, new_id, self)
        self.display.out_queue.append((self.pack_arguments(2, new_id), ()))
        return touch

    def handle_name(self, name):
        """ unique identifier for this seat
        
        In a multiseat configuration this can be used by the client to help
        identify which physical devices the seat represents. Based on
        the seat configuration used by the compositor.
        
        """
        pass

    def release(self):
        """ release the seat object
        
        Using this request a client can tell the server that it is not going to
        use the seat object anymore.
        
        """
        self.display.out_queue.append((self.pack_arguments(3), ()))

    def unpack_event(self, op, data, fds):
        if op == 0:
            return self, op, struct.unpack("I", data)
        elif op == 1:
            return self, op, (data[4:1+struct.unpack("I", data[:4])[0]],)

    def handle_pointer(self, serial, time, button, state):
        pass

    def handle_enter(self, serial, surface, surface_x, surface_y):
        pass

    def handle_leave(self, serial, surface):
        pass

    def handle_motion(self, time, surface_x, surface_y):
        pass

    def handle_button(self, serial, time, button, state):
        pass

    def handle_key(self, serial, time, keysym, state):
        pass

    events = ['capabilities', 'name']
    requests = ['get_pointer', 'get_keyboard', 'get_touch', 'release']


class Pointer(WaylandObject):
    ROLE = 0

    def __init__(self, display, obj_id, seat):
        WaylandObject.__init__(self, display, obj_id)
        self.seat = seat

    def set_cursor(self, serial, surface, hotspot_x, hotspot_y):
        """ set the pointer surface
        
        Set the pointer surface, i.e., the surface that contains the
        pointer image (cursor). This request gives the surface the role
        of a cursor. If the surface already has another role, it raises
        a protocol error.
        
        The cursor actually changes only if the pointer
        focus for this device is one of the requesting client's surfaces
        or the surface parameter is the current pointer surface. If
        there was a previous surface set with this request it is
        replaced. If surface is NULL, the pointer image is hidden.
        
        The parameters hotspot_x and hotspot_y define the position of
        the pointer surface relative to the pointer location. Its
        top-left corner is always at (x, y) - (hotspot_x, hotspot_y),
        where (x, y) are the coordinates of the pointer location, in
        surface-local coordinates.
        
        On surface.attach requests to the pointer surface, hotspot_x
        and hotspot_y are decremented by the x and y parameters
        passed to the request. Attach must be confirmed by
        wl_surface.commit as usual.
        
        The hotspot can also be updated by passing the currently set
        pointer surface to this request with new values for hotspot_x
        and hotspot_y.
        
        The current and pending input regions of the wl_surface are
        cleared, and wl_surface.set_input_region is ignored until the
        wl_surface is no longer used as the cursor. When the use as a
        cursor ends, the current and pending input regions become
        undefined, and the wl_surface is unmapped.
        
        """
        self.display.out_queue.append((self.pack_arguments(0, serial, surface, hotspot_x, hotspot_y), ()))

    def handle_enter(self, serial, surface, surface_x, surface_y):
        """ enter event
        
        Notification that this seat's pointer is focused on a certain
        surface.
        
        When a seat's focus enters a surface, the pointer image
        is undefined and a client should respond to this event by setting
        an appropriate pointer image with the set_cursor request.
        
        """
        self.seat.handle_enter(serial, surface, surface_x, surface_y)

    def handle_leave(self, serial, surface):
        """ leave event
        
        Notification that this seat's pointer is no longer focused on
        a certain surface.
        
        The leave notification is sent before the enter notification
        for the new focus.
        
        """
        self.seat.handle_leave(serial, surface)

    def handle_motion(self, time, surface_x, surface_y):
        """ pointer motion event
        
        Notification of pointer location change. The arguments
        surface_x and surface_y are the location relative to the
        focused surface.
        
        """
        self.seat.handle_motion(time, surface_x, surface_y)

    # physical button state
    RELEASED = 0
    PRESSED = 1

    def handle_button(self, serial, time, button, state):
        """ pointer button event
        
        Mouse button click and release notifications.
        
        The location of the click is given by the last motion or
        enter event.
        The time argument is a timestamp with millisecond
        granularity, with an undefined base.
        
        The button is a button code as defined in the Linux kernel's
        linux/input-event-codes.h header file, e.g. BTN_LEFT.
        
        Any 16-bit button code value is reserved for future additions to the
        kernel's event code list. All other button codes above 0xFFFF are
        currently undefined but may be used in future versions of this
        protocol.
        
        """
        self.seat.handle_button(serial, time, button, state)

    # axis types
    VERTICAL_SCROLL = 0
    HORIZONTAL_SCROLL = 1

    def handle_axis(self, time, axis, value):
        """ axis event
        
        Scroll and other axis notifications.
        
        For scroll events (vertical and horizontal scroll axes), the
        value parameter is the length of a vector along the specified
        axis in a coordinate space identical to those of motion events,
        representing a relative movement along the specified axis.
        
        For devices that support movements non-parallel to axes multiple
        axis events will be emitted.
        
        When applicable, for example for touch pads, the server can
        choose to emit scroll events where the motion vector is
        equivalent to a motion event vector.
        
        When applicable, a client can transform its content relative to the
        scroll distance.
        
        """
        pass

    def release(self):
        """ release the pointer object
        
        Using this request a client can tell the server that it is not going to
        use the pointer object anymore.
        
        This request destroys the pointer proxy object, so clients must not call
        wl_pointer_destroy() after using this request.
        
        """
        self.display.out_queue.append((self.pack_arguments(1), ()))

    def handle_frame(self):
        """ end of a pointer event sequence
        
        Indicates the end of a set of events that logically belong together.
        A client is expected to accumulate the data in all events within the
        frame before proceeding.
        
        All wl_pointer events before a wl_pointer.frame event belong
        logically together. For example, in a diagonal scroll motion the
        compositor will send an optional wl_pointer.axis_source event, two
        wl_pointer.axis events (horizontal and vertical) and finally a
        wl_pointer.frame event. The client may use this information to
        calculate a diagonal vector for scrolling.
        
        When multiple wl_pointer.axis events occur within the same frame,
        the motion vector is the combined motion of all events.
        When a wl_pointer.axis and a wl_pointer.axis_stop event occur within
        the same frame, this indicates that axis movement in one axis has
        stopped but continues in the other axis.
        When multiple wl_pointer.axis_stop events occur within the same
        frame, this indicates that these axes stopped in the same instance.
        
        A wl_pointer.frame event is sent for every logical event group,
        even if the group only contains a single wl_pointer event.
        Specifically, a client may get a sequence: motion, frame, button,
        frame, axis, frame, axis_stop, frame.
        
        The wl_pointer.enter and wl_pointer.leave events are logical events
        generated by the compositor and not the hardware. These events are
        also grouped by a wl_pointer.frame. When a pointer moves from one
        surface to another, a compositor should group the
        wl_pointer.leave event within the same wl_pointer.frame.
        However, a client must not rely on wl_pointer.leave and
        wl_pointer.enter being in the same wl_pointer.frame.
        Compositor-specific policies may require the wl_pointer.leave and
        wl_pointer.enter event being split across multiple wl_pointer.frame
        groups.
        
        """
        pass

    # axis source types
    WHEEL = 0
    FINGER = 1
    CONTINUOUS = 2
    WHEEL_TILT = 3

    def handle_axis_source(self, axis_source):
        """ axis source event
        
        Source information for scroll and other axes.
        
        This event does not occur on its own. It is sent before a
        wl_pointer.frame event and carries the source information for
        all events within that frame.
        
        The source specifies how this event was generated. If the source is
        wl_pointer.axis_source.finger, a wl_pointer.axis_stop event will be
        sent when the user lifts the finger off the device.
        
        If the source is wl_pointer.axis_source.wheel,
        wl_pointer.axis_source.wheel_tilt or
        wl_pointer.axis_source.continuous, a wl_pointer.axis_stop event may
        or may not be sent. Whether a compositor sends an axis_stop event
        for these sources is hardware-specific and implementation-dependent;
        clients must not rely on receiving an axis_stop event for these
        scroll sources and should treat scroll sequences from these scroll
        sources as unterminated by default.
        
        This event is optional. If the source is unknown for a particular
        axis event sequence, no event is sent.
        Only one wl_pointer.axis_source event is permitted per frame.
        
        The order of wl_pointer.axis_discrete and wl_pointer.axis_source is
        not guaranteed.
        
        """
        pass

    def handle_axis_stop(self, time, axis):
        """ axis stop event
        
        Stop notification for scroll and other axes.
        
        For some wl_pointer.axis_source types, a wl_pointer.axis_stop event
        is sent to notify a client that the axis sequence has terminated.
        This enables the client to implement kinetic scrolling.
        See the wl_pointer.axis_source documentation for information on when
        this event may be generated.
        
        Any wl_pointer.axis events with the same axis_source after this
        event should be considered as the start of a new axis motion.
        
        The timestamp is to be interpreted identical to the timestamp in the
        wl_pointer.axis event. The timestamp value may be the same as a
        preceding wl_pointer.axis event.
        
        """
        pass

    def handle_axis_discrete(self, axis, discrete):
        """ axis click event
        
        Discrete step information for scroll and other axes.
        
        This event carries the axis value of the wl_pointer.axis event in
        discrete steps (e.g. mouse wheel clicks).
        
        This event does not occur on its own, it is coupled with a
        wl_pointer.axis event that represents this axis value on a
        continuous scale. The protocol guarantees that each axis_discrete
        event is always followed by exactly one axis event with the same
        axis number within the same wl_pointer.frame. Note that the protocol
        allows for other events to occur between the axis_discrete and
        its coupled axis event, including other axis_discrete or axis
        events.
        
        This event is optional; continuous scrolling devices
        like two-finger scrolling on touchpads do not have discrete
        steps and do not generate this event.
        
        The discrete value carries the directional information. e.g. a value
        of -2 is two steps towards the negative direction of this axis.
        
        The axis number is identical to the axis number in the associated
        axis event.
        
        The order of wl_pointer.axis_discrete and wl_pointer.axis_source is
        not guaranteed.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        if op == 0:
            return self, op, struct.unpack("IIII", data)
        elif op == 1:
            return self, op, struct.unpack("II", data)
        elif op == 2:
            return self, op, struct.unpack("III", data)
        elif op == 3:
            return self, op, struct.unpack("IIII", data)
        elif op == 4:
            return self, op, struct.unpack("III", data)
        elif op == 5:
            return self, op, ()
        elif op == 6:
            return self, op, struct.unpack("I", data)
        elif op == 7:
            return self, op, struct.unpack("II", data)
        elif op == 8:
            return self, op, struct.unpack("II", data)

    events = ['enter', 'leave', 'motion', 'button', 'axis', 'frame', 'axis_source', 'axis_stop', 'axis_discrete']
    requests = ['set_cursor', 'release']


class Keyboard(WaylandObject):
    SHIFT = 1
    CAPS_LOCK = 2
    CONTROL = 4
    ALT = 8
    NUM_LOCK = 16

    def __init__(self, display, obj_id, seat):
        WaylandObject.__init__(self, display, obj_id)
        self.seat = seat
        self.keymap = None
        self.keys = {}
        self.modifiers = None
        self.minimum = 0

    # keyboard mapping format
    NO_KEYMAP = 0
    XKB_V1 = 1

    def handle_keymap(self, format, fd, size):
        """ keyboard mapping
        
        This event provides a file descriptor to the client which can be
        memory-mapped to provide a keyboard mapping description.
        
        """
        if format == self.XKB_V1:
            print(size)
            with os.fdopen(fd) as keymap:
                keymap.seek(0)
                self.keymap = keymap.read(size)
                print(len(self.keymap))
            self.parse_keymap()

    def handle_enter(self, serial, surface, keys):
        """ enter event
        
        Notification that this seat's keyboard focus is on a certain
        surface.
        
        """
        pass

    def handle_leave(self, serial, surface):
        """ leave event
        
        Notification that this seat's keyboard focus is no longer on
        a certain surface.
        
        The leave notification is sent before the enter notification
        for the new focus.
        
        """
        pass

    # physical key state
    RELEASED = 0
    PRESSED = 1

    def handle_key(self, serial, time, key, state):
        """ key event
        
        A key was pressed or released.
        The time argument is a timestamp with millisecond
        granularity, with an undefined base.
        
        """
        key = self.keys[key + self.minimum]
        max_modifiers = len(bin(len(key))) - 2
        abs_modifiers = 2 ** max_modifiers - 1
        keysym = key[self.modifiers & abs_modifiers]
        self.seat.handle_key(serial, time, keysym, state)

    def handle_modifiers(self, serial, mods_depressed, mods_latched, mods_locked, group):
        """ modifier and group state
        
        Notifies clients that the modifier and/or group state has
        changed, and it should update its local state.
        
        """
        self.modifiers = mods_depressed | mods_latched | mods_locked

    def release(self):
        """ release the keyboard object"""
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def handle_repeat_info(self, rate, delay):
        """ repeat rate and delay
        
        Informs the client about the keyboard's repeat rate and delay.
        
        This event is sent as soon as the wl_keyboard object has been created,
        and is guaranteed to be received by the client before any key press
        event.
        
        Negative values for either rate or delay are illegal. A rate of zero
        will disable any repeating (regardless of the value of delay).
        
        This event can be sent later on as well with a new value if necessary,
        so clients should continue listening for the event past the creation
        of wl_keyboard.
        
        """
        pass

    def unpack_event(self, op, data, fds):
        if op == 0:
            return self, op, (struct.unpack("I", data[:4])[0], fds.pop(0), struct.unpack("I", data[4:])[0])
        elif op == 1:
            serial, surface_id, length = struct.unpack("III", data[:12])
            surface = self.display.objects[surface_id]
            return self, op, (serial, surface, [])
        elif op == 2:
            return self, op, struct.unpack("II", data)
        elif op == 3:
            return self, op, struct.unpack("IIII", data)
        elif op == 4:
            return self, op, struct.unpack("IIIII", data)
        elif op == 5:
            return self, op, struct.unpack("ii", data)

    def parse_keymap(self):
        words = [w for w in self.keymap.split() if w]
        key_indices = {}
        index = 0
        while index < len(words):
            if words[index].startswith("<"):
                word = words[index]
                index += 2
                number = words[index].strip(";")
                if number.isdigit():
                    key_indices[word] = int(number)
                index += 1
            elif words[index] == "key":
                index += 1
                symbol = key_indices[words[index]]
                index += 1
                assert words[index] == "{", "Invalid xkb file"
                while words[index] != "[":
                    index += 1
                symbols = []
                index += 1
                while words[index] != "]":
                    symbols.append(words[index].strip(","))
                    index += 1
                while words[index] != "};":
                    index += 1
                self.keys[symbol] = symbols
                index += 1
            elif words[index] == "minimum":
                index += 2
                self.minimum = int(words[index].strip(";"))
                index += 1
            else:
                index += 1

    events = ['keymap', 'enter', 'leave', 'key', 'modifiers', 'repeat_info']
    requests = ['release']


class Touch(WaylandObject):
    def __init__(self, display, obj_id, seat):
        WaylandObject.__init__(self, display, obj_id)
        self.seat = seat

    def handle_down(self, serial, time, surface, id, x, y):
        """ touch down event and beginning of a touch sequence
        
        A new touch point has appeared on the surface. This touch point is
        assigned a unique ID. Future events from this touch point reference
        this ID. The ID ceases to be valid after a touch up event and may be
        reused in the future.
        
        """
        pass

    def handle_up(self, serial, time, id):
        """ end of a touch event sequence
        
        The touch point has disappeared. No further events will be sent for
        this touch point and the touch point's ID is released and may be
        reused in a future touch down event.
        
        """
        pass

    def handle_motion(self, time, id, x, y):
        """ update of touch point coordinates
        
        A touch point has changed coordinates.
        
        """
        pass

    def handle_frame(self):
        """ end of touch frame event
        
        Indicates the end of a set of events that logically belong together.
        A client is expected to accumulate the data in all events within the
        frame before proceeding.
        
        A wl_touch.frame terminates at least one event but otherwise no
        guarantee is provided about the set of events within a frame. A client
        must assume that any state not updated in a frame is unchanged from the
        previously known state.
        
        """
        pass

    def handle_cancel(self):
        """ touch session cancelled
        
        Sent if the compositor decides the touch stream is a global
        gesture. No further events are sent to the clients from that
        particular gesture. Touch cancellation applies to all touch points
        currently active on this client's surface. The client is
        responsible for finalizing the touch points, future touch points on
        this surface may reuse the touch point ID.
        
        """
        pass

    def release(self):
        """ release the touch object"""
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def handle_shape(self, id, major, minor):
        """ update shape of touch point
        
        Sent when a touchpoint has changed its shape.
        
        This event does not occur on its own. It is sent before a
        wl_touch.frame event and carries the new shape information for
        any previously reported, or new touch points of that frame.
        
        Other events describing the touch point such as wl_touch.down,
        wl_touch.motion or wl_touch.orientation may be sent within the
        same wl_touch.frame. A client should treat these events as a single
        logical touch point update. The order of wl_touch.shape,
        wl_touch.orientation and wl_touch.motion is not guaranteed.
        A wl_touch.down event is guaranteed to occur before the first
        wl_touch.shape event for this touch ID but both events may occur within
        the same wl_touch.frame.
        
        A touchpoint shape is approximated by an ellipse through the major and
        minor axis length. The major axis length describes the longer diameter
        of the ellipse, while the minor axis length describes the shorter
        diameter. Major and minor are orthogonal and both are specified in
        surface-local coordinates. The center of the ellipse is always at the
        touchpoint location as reported by wl_touch.down or wl_touch.move.
        
        This event is only sent by the compositor if the touch device supports
        shape reports. The client has to make reasonable assumptions about the
        shape if it did not receive this event.
        
        """
        pass

    def handle_orientation(self, id, orientation):
        """ update orientation of touch point
        
        Sent when a touchpoint has changed its orientation.
        
        This event does not occur on its own. It is sent before a
        wl_touch.frame event and carries the new shape information for
        any previously reported, or new touch points of that frame.
        
        Other events describing the touch point such as wl_touch.down,
        wl_touch.motion or wl_touch.shape may be sent within the
        same wl_touch.frame. A client should treat these events as a single
        logical touch point update. The order of wl_touch.shape,
        wl_touch.orientation and wl_touch.motion is not guaranteed.
        A wl_touch.down event is guaranteed to occur before the first
        wl_touch.orientation event for this touch ID but both events may occur
        within the same wl_touch.frame.
        
        The orientation describes the clockwise angle of a touchpoint's major
        axis to the positive surface y-axis and is normalized to the -180 to
        +180 degree range. The granularity of orientation depends on the touch
        device, some devices only support binary rotation values between 0 and
        90 degrees.
        
        This event is only sent by the compositor if the touch device supports
        orientation reports.
        
        """
        pass

    events = ['down', 'up', 'motion', 'frame', 'cancel', 'shape', 'orientation']
    requests = ['release']


class Output(WaylandObject):

    # subpixel geometry information
    UNKNOWN = 0
    NONE = 1
    HORIZONTAL_RGB = 2
    HORIZONTAL_BGR = 3
    VERTICAL_RGB = 4
    VERTICAL_BGR = 5

    # transform from framebuffer to output
    NORMAL = 0
    ROT_90 = 1
    ROT_180 = 2
    ROT_270 = 3
    FLIPPED = 4
    FLIPPED_90 = 5
    FLIPPED_180 = 6
    FLIPPED_270 = 7

    def handle_geometry(self, x, y, physical_width, physical_height, subpixel, make, model, transform):
        """ properties of the output
        
        The geometry event describes geometric properties of the output.
        The event is sent when binding to the output object and whenever
        any of the properties change.
        
        """
        pass

    # mode information
    CURRENT = 0x1
    PREFERRED = 0x2

    def handle_mode(self, flags, width, height, refresh):
        """ advertise available modes for the output
        
        The mode event describes an available mode for the output.
        
        The event is sent when binding to the output object and there
        will always be one mode, the current mode.  The event is sent
        again if an output changes mode, for the mode that is now
        current.  In other words, the current mode is always the last
        mode that was received with the current flag set.
        
        The size of a mode is given in physical hardware units of
        the output device. This is not necessarily the same as
        the output size in the global compositor space. For instance,
        the output may be scaled, as described in wl_output.scale,
        or transformed, as described in wl_output.transform.
        
        """
        pass

    def handle_done(self):
        """ sent all information about output
        
        This event is sent after all other properties have been
        sent after binding to the output object and after any
        other property changes done after that. This allows
        changes to the output properties to be seen as
        atomic, even if they happen via multiple events.
        
        """
        pass

    def handle_scale(self, factor):
        """ output scaling properties
        
        This event contains scaling geometry information
        that is not in the geometry event. It may be sent after
        binding the output object or if the output scale changes
        later. If it is not sent, the client should assume a
        scale of 1.
        
        A scale larger than 1 means that the compositor will
        automatically scale surface buffers by this amount
        when rendering. This is used for very high resolution
        displays where applications rendering at the native
        resolution would be too small to be legible.
        
        It is intended that scaling aware clients track the
        current output of a surface, and if it is on a scaled
        output it should use wl_surface.set_buffer_scale with
        the scale of the output. That way the compositor can
        avoid scaling the surface, and the client can supply
        a higher detail image.
        
        """
        pass

    def release(self):
        """ release the output object
        
        Using this request a client can tell the server that it is not going to
        use the output object anymore.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def unpack_event(self, op, data, fds):
        if op == 0:
            x, y, width, height, subpixel, length = struct.unpack("IIIIII", data[:24])
            make = data[24:length+24].decode("utf-8")
            offset = 24 + 4*((length + 3) // 4)
            length = struct.unpack("I", data[offset:offset+4])[0]
            model = data[offset+4:offset+4+length]
            offset = offset + 4 + 4*((length + 3) // 4)
            transform = struct.unpack("I", data[offset:])[0]
            return self, op, (x, y, width, height, subpixel, make, model, transform)
        elif op == 1:
            return self, op, struct.unpack("IIII", data)
        elif op == 2:
            return self, op, ()
        elif op == 3:
            return self, op, struct.unpack("I", data)

    events = ['geometry', 'mode', 'done', 'scale']
    requests = ['release']


class Region(WaylandObject):

    def destroy(self):
        """ destroy region
        
        Destroy the region.  This will invalidate the object ID.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def add(self, x, y, width, height):
        """ add rectangle to region
        
        Add the specified rectangle to the region.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, x, y, width, height), ()))

    def subtract(self, x, y, width, height):
        """ subtract rectangle from region
        
        Subtract the specified rectangle from the region.
        
        """
        self.display.out_queue.append((self.pack_arguments(2, x, y, width, height), ()))

    events = []
    requests = ['destroy', 'add', 'subtract']


class Subcompositor(WaylandObject):

    def destroy(self):
        """ unbind from the subcompositor interface
        
        Informs the server that the client will not be using this
        protocol object anymore. This does not affect any other
        objects, wl_subsurface objects included.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))
    BAD_SURFACE = 0

    def get_subsurface(self, surface, parent):
        """ give a surface the role sub-surface
        
        Create a sub-surface interface for the given surface, and
        associate it with the given parent surface. This turns a
        plain wl_surface into a sub-surface.
        
        The to-be sub-surface must not already have another role, and it
        must not have an existing wl_subsurface object. Otherwise a protocol
        error is raised.
        
        """
        new_id = self.display.next_id()
        subsurface = Subsurface(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(1, new_id, surface, parent), ()))
        return subsurface

    events = []
    requests = ['destroy', 'get_subsurface']


class Subsurface(WaylandObject):

    def destroy(self):
        """ remove sub-surface interface
        
        The sub-surface interface is removed from the wl_surface object
        that was turned into a sub-surface with a
        wl_subcompositor.get_subsurface request. The wl_surface's association
        to the parent is deleted, and the wl_surface loses its role as
        a sub-surface. The wl_surface is unmapped.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))
    BAD_SURFACE = 0

    def set_position(self, x, y):
        """ reposition the sub-surface
        
        This schedules a sub-surface position change.
        The sub-surface will be moved so that its origin (top left
        corner pixel) will be at the location x, y of the parent surface
        coordinate system. The coordinates are not restricted to the parent
        surface area. Negative values are allowed.
        
        The scheduled coordinates will take effect whenever the state of the
        parent surface is applied. When this happens depends on whether the
        parent surface is in synchronized mode or not. See
        wl_subsurface.set_sync and wl_subsurface.set_desync for details.
        
        If more than one set_position request is invoked by the client before
        the commit of the parent surface, the position of a new request always
        replaces the scheduled position from any previous request.
        
        The initial position is 0, 0.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, x, y), ()))

    def place_above(self, sibling):
        """ restack the sub-surface
        
        This sub-surface is taken from the stack, and put back just
        above the reference surface, changing the z-order of the sub-surfaces.
        The reference surface must be one of the sibling surfaces, or the
        parent surface. Using any other surface, including this sub-surface,
        will cause a protocol error.
        
        The z-order is double-buffered. Requests are handled in order and
        applied immediately to a pending state. The final pending state is
        copied to the active state the next time the state of the parent
        surface is applied. When this happens depends on whether the parent
        surface is in synchronized mode or not. See wl_subsurface.set_sync and
        wl_subsurface.set_desync for details.
        
        A new sub-surface is initially added as the top-most in the stack
        of its siblings and parent.
        
        """
        self.display.out_queue.append((self.pack_arguments(2, sibling), ()))

    def place_below(self, sibling):
        """ restack the sub-surface
        
        The sub-surface is placed just below the reference surface.
        See wl_subsurface.place_above.
        
        """
        self.display.out_queue.append((self.pack_arguments(3, sibling), ()))

    def set_sync(self):
        """ set sub-surface to synchronized mode
        
        Change the commit behaviour of the sub-surface to synchronized
        mode, also described as the parent dependent mode.
        
        In synchronized mode, wl_surface.commit on a sub-surface will
        accumulate the committed state in a cache, but the state will
        not be applied and hence will not change the compositor output.
        The cached state is applied to the sub-surface immediately after
        the parent surface's state is applied. This ensures atomic
        updates of the parent and all its synchronized sub-surfaces.
        Applying the cached state will invalidate the cache, so further
        parent surface commits do not (re-)apply old state.
        
        See wl_subsurface for the recursive effect of this mode.
        
        """
        self.display.out_queue.append((self.pack_arguments(4), ()))

    def set_desync(self):
        """ set sub-surface to desynchronized mode
        
        Change the commit behaviour of the sub-surface to desynchronized
        mode, also described as independent or freely running mode.
        
        In desynchronized mode, wl_surface.commit on a sub-surface will
        apply the pending state directly, without caching, as happens
        normally with a wl_surface. Calling wl_surface.commit on the
        parent surface has no effect on the sub-surface's wl_surface
        state. This mode allows a sub-surface to be updated on its own.
        
        If cached state exists when wl_surface.commit is called in
        desynchronized mode, the pending state is added to the cached
        state, and applied as a whole. This invalidates the cache.
        
        Note: even if a sub-surface is set to desynchronized, a parent
        sub-surface may override it to behave as synchronized. For details,
        see wl_subsurface.
        
        If a surface's parent surface behaves as desynchronized, then
        the cached state is applied on set_desync.
        
        """
        self.display.out_queue.append((self.pack_arguments(5), ()))

    events = []
    requests = ['destroy', 'set_position', 'place_above', 'place_below', 'set_sync', 'set_desync']
