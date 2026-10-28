"""In-memory fake of the winreg bits contextmenu.py uses (for tests)."""


class FakeWinreg:
    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    KEY_READ = 0x20019
    KEY_WRITE = 0x20006

    def __init__(self):
        # path -> {"values": {name: (value, type)}, "children": set(names)}
        self._tree = {"": {"values": {}, "children": set()}}

    # -- helpers ------------------------------------------------------
    def _norm(self, path):
        return path.replace("/", "\\")

    def _ensure(self, path):
        path = self._norm(path)
        if path in self._tree:
            return
        parent, _, _ = path.rpartition("\\")
        self._ensure(parent)
        self._tree[path] = {"values": {}, "children": set()}
        self._tree[parent]["children"].add(path.rpartition("\\")[2])

    def _get(self, path):
        path = self._norm(path)
        if path not in self._tree:
            raise FileNotFoundError(path)
        return self._tree[path]

    class _Key:
        def __init__(self, fake, path):
            self._fake = fake
            self._path = path

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    # -- winreg API surface used by contextmenu --------------------------
    def CreateKey(self, root, subkey):
        self._ensure(subkey)
        return self._Key(self, self._norm(subkey))

    def OpenKey(self, root, subkey, reserved=0, access=0):
        node = self._get(subkey)  # noqa: F841 - raises if missing
        return self._Key(self, self._norm(subkey))

    def SetValueEx(self, key, name, reserved, typ, value):
        self._tree[key._path]["values"][name or ""] = (value, typ)

    def QueryValueEx(self, key, name):
        try:
            return self._tree[key._path]["values"][name or ""]
        except KeyError:
            raise FileNotFoundError(name or "(Default)")

    def EnumKey(self, key, index):
        children = sorted(self._tree[key._path]["children"])
        if index >= len(children):
            raise OSError("no more subkeys")
        return children[index]

    def DeleteKey(self, root, subkey):
        node = self._get(subkey)
        if node["children"]:
            raise OSError("key has subkeys")
        path = self._norm(subkey)
        parent, _, leaf = path.rpartition("\\")
        del self._tree[path]
        self._tree[parent]["children"].discard(leaf)
