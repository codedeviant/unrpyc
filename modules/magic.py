# Copyright (c) 2014 CensoredUsername
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# This module uses magic to make it possible to unpickle files
# even though the necessary modules cannot be imported

import sys
from types import ModuleType
from pickle import Unpickler
from cStringIO import StringIO

# the main API

def load(file):
    return FakeUnPickler(file).load()

def loads(string):
    return load(StringIO(string))

def fake_package(name):
    # Mount a fake package tree. This means that any request to import
    # From a submodule of this package will be served a fake package.
    # Next to this any real module which would be somewhere
    # within this package will be ignored in favour of a fake one
    mod = FakePackage(name)
    sys.meta_path.append(mod)
    return mod

# A dict of name: __bases__, {methodname: function}
specials = {}

# Fake class implementation

class FakeClassType(type):
    # We create a new type for the fake classes so they can be compared with fakemodules
    # and will return true when they are located at the same path
    # this allows to define datastructures using the the objects autogenerated from
    # fake modules and then use these to test agains fake classes
    def __eq__(self, other):
        return hasattr(other, __name__) and self.__module__ + "." + self.__name__ == other.__name__
    def __hash__(self):
        return hash(self.__module__ + "." + self.__name__)

def FakeClass(name, module):
    # A fake class with special __new__ and __setstate__ methods which try to
    # Reslove creation without requiring any information except the pickled data
    parent, new_methods = specials.get(module + "." + name, ((object,), None))

    methods = default_methods.copy()
    if new_methods:
        methods.update(new_methods)

    klass = FakeClassType(name, parent, methods)
    klass.__module__ = module
    klass.__name__ = name
    return klass

# General new and setstate methods for fake classes

def _new(cls, *args):
    self = cls.__bases__[0].__new__(cls)
    if args:
        print "{} got __new__() arguments {} but does not know how to handle them".format(str(cls), str(args))
        self._new_args = args
    return self

def _setstate(self, state):
    slotstate = None

    if (isinstance(state, tuple) and len(state) == 2 and 
        (state[0] is None or isinstance(state[0], dict)) and
        (state[1] is None or isinstance(state[1], dict))):
        state, slotstate = state
    
    if state:
        # Don't have to check for slotstate here since it's either None or a dict
        if not isinstance(state, dict):
            print "{} instance got __setstate__() arguments {} but does not know how to handle them".format(str(self.__class__), str(state))
            self._setstate_args = state 
        else:
            self.__dict__.update(state)
        
    if slotstate:
        self.__dict__.update(slotstate)

default_methods = {
    "__new__": _new,
    "__setstate__": _setstate
}

# Fake module implementation

class FakeModule(ModuleType):
    # A dynamically created module which adds itself to sys.modules, pretending to be a real one
    def __init__(self, name):
        super(FakeModule, self).__init__(name)
        sys.modules[name] = self

    def __repr__(self):
        return "<module '{}' (fake)>".format(self.__name__)

    def __setattr__(self, name, value):
        # If a fakemodule is removed we need to remove its entry from sys.modules
        if name in self.__dict__ and isinstance(self.__dict__[name], FakeModule) and not isinstance(value, FakeModule):
            self.__dict__[name]._remove()
        self.__dict__[name] = value

    def _remove(self):
        for i in self.__dict__:
            if isinstance(i, FakeModule):
                i._remove()
        del sys.modules[self.__name__]

    def __eq__(self, other):
        if not hasattr(other, "__name__"):
            return False
        othername = other.__name__
        if hasattr(other, "__module__"):
            othername = other.__module__ + "." + other.__name__

        return self.__name__ == othername

    def __hash__(self):
        return hash(self.__name__)

class FakePackage(FakeModule):
    # a dynamically created module which pretends it's a real one, and it will create any requested
    # submodule as another FakePackage
    __path__ = []

    @classmethod
    def load_module(cls, fullname):
        return cls(fullname)

    def find_module(self, fullname, path=None):
        if fullname.startswith(self.__name__ + "."):
            return FakePackage
        else:
            return None

    def __getattr__(self, name):
        modname = self.__name__ + "." + name
        mod = sys.modules.get(modname, None)
        if mod is None:
            try: 
                __import__(modname)
            except:
                mod = FakePackage(modname)
            else:
                mod = sys.modules[modname]
        return mod

class FakeUnPickler(Unpickler):
    # A picler which, instead of failing after trying to import
    # A module, creates a fake module which serves fake objects
    def find_class(self, module, name):
        mod = sys.modules.get(module, None)
        if mod is None:
            try:
                __import__(module)
            except:
                mod = FakeModule(module)
                print "Created module {}".format(str(mod))
            else:
                mod = sys.modules[module]

        klass = getattr(mod, name, None)
        if klass is None or isinstance(klass, FakeModule):
            klass = FakeClass(name, module)
            setattr(mod, name, klass)

        return klass

# special new and setstate methods for special classes

def PyExprNew(cls, s, filename, linenumber):
    self = unicode.__new__(cls, s)
    self.filename = filename
    self.linenumber = linenumber
    return self

def PyCodeSetstate(self, state):
    (_, self.source, self.location, self.mode) = state
    self.bytecode = None

# there are two classes which require special treatment
# renpy.ast.PyExpr because, for all purposes, it inherits from unicode
# renpy.PyCode, because it uses setstate
specials["renpy.ast.PyExpr"] = ((unicode,), {"__new__": PyExprNew})
specials["renpy.ast.PyCode"] = ((object,), {"__setstate__": PyCodeSetstate})

