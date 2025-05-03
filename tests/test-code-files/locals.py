# pylint: skip-file

f = 1


class z:
    def __init__(self):
        self.x = 1
        self.y = 2
        self.z = 3
        self.m = 4
        self.n = 5
        self.u = 1

    class b:
        c = 1

    def a(*args):
        pass


u = {
    1: 1,
    2: 2,
    3: 3,
    4: 4,
    5: 5,
    6: 6,
}
u1 = [0]


def a(*args):
    global f
    b = 1
    c = 2
    d = 3
    f = 1
    z.b.c = 2
    u["name"] = 3
    u1[0] = 3


a(1, 2, 3, 4)

z().a(5, 6, 7)
print(z().__class__.__name__)
"a".startswith("a")
print(z().__dict__)

print(z())
