from xml.etree import ElementTree


def convert_name(name):
    if name.startswith("wl_"):
        name = name[3:]
    name = name[0].upper() + name[1:]
    while "_" in name:
        index = name.index("_")
        name = name[:index] + name[index+1].upper() + name[index+2:]
    return name


def main():
    e = ElementTree.ElementTree()
    e.parse("/home/john/wayland/protocol/wayland.xml")
    wayland_copyright = None
    interfaces = []
    for element in e.getroot():
        if element.tag == "copyright":
            wayland_copyright = element
        elif element.tag == "interface":
            interfaces.append(element)
    with open("server.py", "w") as wayland:
        wayland.write('"""')
        wayland.write(wayland_copyright.text)
        wayland.write('\n"""\n\nfrom .base import WaylandObject\n')
        for interface in interfaces:
            handle_interface(interface, wayland)


def handle_interface(interface, wayland):
    wayland.write("\n\nclass ")
    name = convert_name(interface.get("name"))
    wayland.write(name)
    wayland.write("(WaylandObject):\n")
    events = []
    requests = []
    for child in interface:
        if child.tag == "event":
            handle_request(child, len(requests), wayland)
            requests.append(child)
        elif child.tag == "request":
            handle_event(child, wayland)
            events.append(child)
        elif child.tag == "enum":
            handle_enum(child, wayland)
    wayland.write("\n    events = {}".format([e.get("name") for e in events]))
    wayland.write("\n    requests = {}\n".format([r.get("name")for r in requests]))


def handle_request(request, index, wayland):
    wayland.write("\n    def send_{}(self".format(request.get("name")))
    description = None
    arguments = []
    for c in request:
        if c.tag == "description":
            description = c
        elif c.tag == "arg":
            arguments.append(c)
    new_id = None
    for arg in arguments:
        if arg.get("type") == "new_id":
            new_id = arg
        else:
            wayland.write(", {}".format(arg.get("name")))
    wayland.write('):\n        """ {}'.format(description.get("summary")))
    if description.text is not None:
        wayland.write("\n        ")
        for line in description.text.splitlines():
            wayland.write("{}\n        ".format(line.strip()))
    wayland.write('"""\n')
    if new_id is not None:
        wayland.write("        new_id = self.display.next_id()\n")
        cls = convert_name(new_id.get("interface") or "wl_compositor")
        name = new_id.get("name")
        if name == "id":
            name = (new_id.get("interface") or "wl_compositor")[3:]
        wayland.write("        {} = {}(self.display, new_id)\n".format(name, cls))
    wayland.write("        self.display.out_queue.append((self.pack_arguments({}".format(index))
    fds = []
    for i, arg in enumerate(arguments):
        if arg.get("type") == "new_id":
            wayland.write(", new_id")
        elif arg.get("type") == "fd":
            fds.append(arg)
            continue
        else:
            wayland.write(", {}".format(arg.get("name")))
    wayland.write("), (")
    for i, fd in enumerate(fds):
        wayland.write(fd.get("name"))
        if i < len(fds) - 1:
            wayland.write(", ")
        elif len(fds) == 1:
            wayland.write(",")
    wayland.write(")))\n")
    if new_id is not None:
        wayland.write("        return {}\n".format(name))


def handle_event(event, wayland):
    wayland.write("\n    def handle_{}(self".format(event.get("name")))
    description = None
    arguments = []
    for c in event:
        if c.tag == "description":
            description = c
        elif c.tag == "arg":
            arguments.append(c)
    for arg in arguments:
        wayland.write(", {}".format(arg.get("name")))
    wayland.write('):\n        ')
    if description is not None:
        wayland.write('""" {}'.format(description.get("summary")))
        if description.text is not None:
            wayland.write("\n        ")
            for line in description.text.splitlines():
                wayland.write("{}\n        ".format(line.strip()))
        wayland.write('"""\n        ')
    wayland.write('pass\n')


def handle_enum(enum, wayland):
    description = None
    values = []
    for c in enum:
        if c.tag == "description":
            description = c
        else:
            values.append(c)
    if description is not None:
        wayland.write("\n    # {}\n".format(description.get("summary")))
    for value in values:
        wayland.write("    {} = {}\n".format(value.get("name").upper(), value.get("value")))


if __name__ == '__main__':
    main()
