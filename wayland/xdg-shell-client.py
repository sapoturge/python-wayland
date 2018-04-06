"""
    Copyright © 2008-2013 Kristian Høgsberg
    Copyright © 2013      Rafael Antognolli
    Copyright © 2013      Jasper St. Pierre
    Copyright © 2010-2013 Intel Corporation

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the "Software"),
    to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense,
    and/or sell copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice (including the next
    paragraph) shall be included in all copies or substantial portions of the
    Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
    THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
  
"""

from base import WaylandObject


class XdgShell(WaylandObject):

    # latest protocol version
    CURRENT = 5
    ROLE = 0
    DEFUNCT_SURFACES = 1
    NOT_THE_TOPMOST_POPUP = 2
    INVALID_POPUP_PARENT = 3

    def destroy(self):
        """ destroy xdg_shell
        
        Destroy this xdg_shell object.
        
        Destroying a bound xdg_shell object while there are surfaces
        still alive created by this xdg_shell object instance is illegal
        and will result in a protocol error.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def use_unstable_version(self, version):
        """ enable use of this unstable version
        
        Negotiate the unstable version of the interface.  This
        mechanism is in place to ensure client and server agree on the
        unstable versions of the protocol that they speak or exit
        cleanly if they don't agree.  This request will go away once
        the xdg-shell protocol is stable.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, version), ()))

    def get_xdg_surface(self, surface):
        """ create a shell surface from a surface
        
        This creates an xdg_surface for the given surface and gives it the
        xdg_surface role. A wl_surface can only be given an xdg_surface role
        once. If get_xdg_surface is called with a wl_surface that already has
        an active xdg_surface associated with it, or if it had any other role,
        an error is raised.
        
        See the documentation of xdg_surface for more details about what an
        xdg_surface is and how it is used.
        
        """
        new_id = self.display.next_id()
        _surface = XdgSurface(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(2, new_id, surface), ()))
        return _surface

    def get_xdg_popup(self, surface, parent, seat, serial, x, y):
        """ create a popup for a surface
        
        This creates an xdg_popup for the given surface and gives it the
        xdg_popup role. A wl_surface can only be given an xdg_popup role
        once. If get_xdg_popup is called with a wl_surface that already has
        an active xdg_popup associated with it, or if it had any other role,
        an error is raised.
        
        This request must be used in response to some sort of user action
        like a button press, key press, or touch down event.
        
        See the documentation of xdg_popup for more details about what an
        xdg_popup is and how it is used.
        
        """
        new_id = self.display.next_id()
        _popup = XdgPopup(self.display, new_id)
        self.display.out_queue.append((self.pack_arguments(3, new_id, surface, parent, seat, serial, x, y), ()))
        return _popup

    def handle_ping(self, serial):
        """ check if the client is alive
        
        The ping event asks the client if it's still alive. Pass the
        serial specified in the event back to the compositor by sending
        a "pong" request back with the specified serial.
        
        Compositors can use this to determine if the client is still
        alive. It's unspecified what will happen if the client doesn't
        respond to the ping request, or in what timeframe. Clients should
        try to respond in a reasonable amount of time.
        
        A compositor is free to ping in any way it wants, but a client must
        always respond to any xdg_shell object it created.
        
        """
        pass

    def pong(self, serial):
        """ respond to a ping event
        
        A client must respond to a ping event with a pong request or
        the client may be deemed unresponsive.
        
        """
        self.display.out_queue.append((self.pack_arguments(4, serial), ()))

    events = ['ping']
    requests = ['destroy', 'use_unstable_version', 'get_xdg_surface', 'get_xdg_popup', 'pong']


class XdgSurface(WaylandObject):

    def destroy(self):
        """ Destroy the xdg_surface
        
        Unmap and destroy the window. The window will be effectively
        hidden from the user's point of view, and all state like
        maximization, fullscreen, and so on, will be lost.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def set_parent(self, parent):
        """ set the parent of this surface
        
        Set the "parent" of this surface. This window should be stacked
        above a parent. The parent surface must be mapped as long as this
        surface is mapped.
        
        Parent windows should be set on dialogs, toolboxes, or other
        "auxiliary" surfaces, so that the parent is raised when the dialog
        is raised.
        
        """
        self.display.out_queue.append((self.pack_arguments(1, parent), ()))

    def set_title(self, title):
        """ set surface title
        
        Set a short title for the surface.
        
        This string may be used to identify the surface in a task bar,
        window list, or other user interface elements provided by the
        compositor.
        
        The string must be encoded in UTF-8.
        
        """
        self.display.out_queue.append((self.pack_arguments(2, title), ()))

    def set_app_id(self, app_id):
        """ set application ID
        
        Set an application identifier for the surface.
        
        The app ID identifies the general class of applications to which
        the surface belongs. The compositor can use this to group multiple
        surfaces together, or to determine how to launch a new application.
        
        For D-Bus activatable applications, the app ID is used as the D-Bus
        service name.
        
        The compositor shell will try to group application surfaces together
        by their app ID.  As a best practice, it is suggested to select app
        ID's that match the basename of the application's .desktop file.
        For example, "org.freedesktop.FooViewer" where the .desktop file is
        "org.freedesktop.FooViewer.desktop".
        
        See the desktop-entry specification [0] for more details on
        application identifiers and how they relate to well-known D-Bus
        names and .desktop files.
        
        [0] http://standards.freedesktop.org/desktop-entry-spec/
        
        """
        self.display.out_queue.append((self.pack_arguments(3, app_id), ()))

    def show_window_menu(self, seat, serial, x, y):
        """ show the window menu
        
        Clients implementing client-side decorations might want to show
        a context menu when right-clicking on the decorations, giving the
        user a menu that they can use to maximize or minimize the window.
        
        This request asks the compositor to pop up such a window menu at
        the given position, relative to the local surface coordinates of
        the parent surface. There are no guarantees as to what menu items
        the window menu contains.
        
        This request must be used in response to some sort of user action
        like a button press, key press, or touch down event.
        
        """
        self.display.out_queue.append((self.pack_arguments(4, seat, serial, x, y), ()))

    def move(self, seat, serial):
        """ start an interactive move
        
        Start an interactive, user-driven move of the surface.
        
        This request must be used in response to some sort of user action
        like a button press, key press, or touch down event. The passed
        serial is used to determine the type of interactive move (touch,
        pointer, etc).
        
        The server may ignore move requests depending on the state of
        the surface (e.g. fullscreen or maximized), or if the passed serial
        is no longer valid.
        
        If triggered, the surface will lose the focus of the device
        (wl_pointer, wl_touch, etc) used for the move. It is up to the
        compositor to visually indicate that the move is taking place, such as
        updating a pointer cursor, during the move. There is no guarantee
        that the device focus will return when the move is completed.
        
        """
        self.display.out_queue.append((self.pack_arguments(5, seat, serial), ()))

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
        
        Start a user-driven, interactive resize of the surface.
        
        This request must be used in response to some sort of user action
        like a button press, key press, or touch down event. The passed
        serial is used to determine the type of interactive resize (touch,
        pointer, etc).
        
        The server may ignore resize requests depending on the state of
        the surface (e.g. fullscreen or maximized).
        
        If triggered, the client will receive configure events with the
        "resize" state enum value and the expected sizes. See the "resize"
        enum value for more details about what is required. The client
        must also acknowledge configure events using "ack_configure". After
        the resize is completed, the client will receive another "configure"
        event without the resize state.
        
        If triggered, the surface also will lose the focus of the device
        (wl_pointer, wl_touch, etc) used for the resize. It is up to the
        compositor to visually indicate that the resize is taking place,
        such as updating a pointer cursor, during the resize. There is no
        guarantee that the device focus will return when the resize is
        completed.
        
        The edges parameter specifies how the surface should be resized,
        and is one of the values of the resize_edge enum. The compositor
        may use this information to update the surface position for
        example when dragging the top left corner. The compositor may also
        use this information to adapt its behavior, e.g. choose an
        appropriate cursor image.
        
        """
        self.display.out_queue.append((self.pack_arguments(6, seat, serial, edges), ()))

    # types of state on the surface
    MAXIMIZED = 1
    FULLSCREEN = 2
    RESIZING = 3
    ACTIVATED = 4

    def handle_configure(self, width, height, states, serial):
        """ suggest a surface change
        
        The configure event asks the client to resize its surface or to
        change its state.
        
        The width and height arguments specify a hint to the window
        about how its surface should be resized in window geometry
        coordinates. See set_window_geometry.
        
        If the width or height arguments are zero, it means the client
        should decide its own window dimension. This may happen when the
        compositor need to configure the state of the surface but doesn't
        have any information about any previous or expected dimension.
        
        The states listed in the event specify how the width/height
        arguments should be interpreted, and possibly how it should be
        drawn.
        
        Clients should arrange their surface for the new size and
        states, and then send a ack_configure request with the serial
        sent in this configure event at some point before committing
        the new surface.
        
        If the client receives multiple configure events before it
        can respond to one, it is free to discard all but the last
        event it received.
        
        """
        pass

    def ack_configure(self, serial):
        """ ack a configure event
        
        When a configure event is received, if a client commits the
        surface in response to the configure event, then the client
        must make an ack_configure request sometime before the commit
        request, passing along the serial of the configure event.
        
        For instance, the compositor might use this information to move
        a surface to the top left only when the client has drawn itself
        for the maximized or fullscreen state.
        
        If the client receives multiple configure events before it
        can respond to one, it only has to ack the last configure event.
        
        A client is not required to commit immediately after sending
        an ack_configure request - it may even ack_configure several times
        before its next surface commit.
        
        The compositor expects that the most recently received
        ack_configure request at the time of a commit indicates which
        configure event the client is responding to.
        
        """
        self.display.out_queue.append((self.pack_arguments(7, serial), ()))

    def set_window_geometry(self, x, y, width, height):
        """ set the new window geometry
        
        The window geometry of a window is its "visible bounds" from the
        user's perspective. Client-side decorations often have invisible
        portions like drop-shadows which should be ignored for the
        purposes of aligning, placing and constraining windows.
        
        The window geometry is double buffered, and will be applied at the
        time wl_surface.commit of the corresponding wl_surface is called.
        
        Once the window geometry of the surface is set once, it is not
        possible to unset it, and it will remain the same until
        set_window_geometry is called again, even if a new subsurface or
        buffer is attached.
        
        If never set, the value is the full bounds of the surface,
        including any subsurfaces. This updates dynamically on every
        commit. This unset mode is meant for extremely simple clients.
        
        If responding to a configure event, the window geometry in here
        must respect the sizing negotiations specified by the states in
        the configure event.
        
        The arguments are given in the surface local coordinate space of
        the wl_surface associated with this xdg_surface.
        
        The width and height must be greater than zero.
        
        """
        self.display.out_queue.append((self.pack_arguments(8, x, y, width, height), ()))

    def set_maximized(self):
        """ maximize the window
        
        Maximize the surface.
        
        After requesting that the surface should be maximized, the compositor
        will respond by emitting a configure event with the "maximized" state
        and the required window geometry. The client should then update its
        content, drawing it in a maximized state, i.e. without shadow or other
        decoration outside of the window geometry. The client must also
        acknowledge the configure when committing the new content (see
        ack_configure).
        
        It is up to the compositor to decide how and where to maximize the
        surface, for example which output and what region of the screen should
        be used.
        
        If the surface was already maximized, the compositor will still emit
        a configure event with the "maximized" state.
        
        """
        self.display.out_queue.append((self.pack_arguments(9), ()))

    def unset_maximized(self):
        """ unmaximize the window
        
        Unmaximize the surface.
        
        After requesting that the surface should be unmaximized, the compositor
        will respond by emitting a configure event without the "maximized"
        state. If available, the compositor will include the window geometry
        dimensions the window had prior to being maximized in the configure
        request. The client must then update its content, drawing it in a
        regular state, i.e. potentially with shadow, etc. The client must also
        acknowledge the configure when committing the new content (see
        ack_configure).
        
        It is up to the compositor to position the surface after it was
        unmaximized; usually the position the surface had before maximizing, if
        applicable.
        
        If the surface was already not maximized, the compositor will still
        emit a configure event without the "maximized" state.
        
        """
        self.display.out_queue.append((self.pack_arguments(10), ()))

    def set_fullscreen(self, output):
        """ set the window as fullscreen on a monitor
        
        Make the surface fullscreen.
        
        You can specify an output that you would prefer to be fullscreen.
        If this value is NULL, it's up to the compositor to choose which
        display will be used to map this surface.
        
        If the surface doesn't cover the whole output, the compositor will
        position the surface in the center of the output and compensate with
        black borders filling the rest of the output.
        
        """
        self.display.out_queue.append((self.pack_arguments(11, output), ()))

    def unset_fullscreen(self):
                self.display.out_queue.append((self.pack_arguments(12), ()))

    def set_minimized(self):
        """ set the window as minimized
        
        Request that the compositor minimize your surface. There is no
        way to know if the surface is currently minimized, nor is there
        any way to unset minimization on this surface.
        
        If you are looking to throttle redrawing when minimized, please
        instead use the wl_surface.frame event for this, as this will
        also work with live previews on windows in Alt-Tab, Expose or
        similar compositor features.
        
        """
        self.display.out_queue.append((self.pack_arguments(13), ()))

    def handle_close(self):
        """ surface wants to be closed
        
        The close event is sent by the compositor when the user
        wants the surface to be closed. This should be equivalent to
        the user clicking the close button in client-side decorations,
        if your application has any...
        
        This is only a request that the user intends to close your
        window. The client may choose to ignore this request, or show
        a dialog to ask the user to save their data...
        
        """
        pass

    events = ['configure', 'close']
    requests = ['destroy', 'set_parent', 'set_title', 'set_app_id', 'show_window_menu', 'move', 'resize', 'ack_configure', 'set_window_geometry', 'set_maximized', 'unset_maximized', 'set_fullscreen', 'unset_fullscreen', 'set_minimized']


class XdgPopup(WaylandObject):

    def destroy(self):
        """ remove xdg_popup interface
        
        This destroys the popup. Explicitly destroying the xdg_popup
        object will also dismiss the popup, and unmap the surface.
        
        If this xdg_popup is not the "topmost" popup, a protocol error
        will be sent.
        
        """
        self.display.out_queue.append((self.pack_arguments(0), ()))

    def handle_popup_done(self):
        """ popup interaction is done
        
        The popup_done event is sent out when a popup is dismissed by the
        compositor. The client should destroy the xdg_popup object at this
        point.
        
        """
        pass

    events = ['popup_done']
    requests = ['destroy']
