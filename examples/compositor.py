import pygame
from wayland import server


class Display(server.Display):
    def __init__(self):
        self.screen = pygame.display.set_mode((640, 480))
        super().__init__(Output(self), Compositor(self))
        print(self.path)


class Compositor(object):
    name = "wl_compositor"
    version = 1

    def __init__(self, display):
        self.display = display

    def setup(self, proxy):
        pass

    def update(self):
        pass


class Output(object):
    name = "wl_output"
    version = 1

    def __init__(self, display):
        self.display = display

    def setup(self, proxy):
        proxy.send_geometry(self.display.screen.get_width(), self.display.screen.get_height(), self.display.screen.get_width(), self.display.screen.get_height(), proxy.UNKNOWN, "None", "None", proxy.NORMAL)

    def update(self):
        pass


def main():
    display = Display()
    try:
        while True:
            display.handle_requests()
            for o in display.global_objects:
                o.update()
    finally:
        import os
        os.remove(display.path)


if __name__ == "__main__":
    main()
