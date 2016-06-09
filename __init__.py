import base64
import ctypes
import datetime
import binascii
from itertools import chain

import base58


class BaseStingyField(object):
    order = 0

    def __init__(self):
        self.name = ''
        self.structure_fields = None
        self.order = BaseStingyField.order
        BaseStingyField.order += 1

    def prepare_structure(self):
        raise NotImplementedError

    def pack(self, value):
        raise NotImplementedError

    def unpack(self, iterator):
        raise NotImplementedError

    def prefix(self, text):
        return "%s_%s" % (self.name, text)


class NumberField(BaseStingyField):
    def __init__(self, max_value=None, num_bits=None):
        super(NumberField, self).__init__()
        assert max_value or num_bits
        self.num_bits = num_bits or len(bin(max_value)[2:])

    def prepare_structure(self):
        type_ = ctypes.c_uint if self.num_bits <= 32 else ctypes.c_ulonglong
        self.structure_fields = [(self.prefix('num'), type_, self.num_bits)]

    def pack(self, value):
        return {self.prefix('num'): value}

    def unpack(self, data):
        return int(getattr(data, self.prefix('num')))


class HexField(BaseStingyField):
    def __init__(self, len):
        assert len % 2 == 0
        super(HexField, self).__init__()
        self.num_bytes = len / 2
        self.array = None

    def prepare_structure(self):
        self.array = ctypes.c_ubyte * self.num_bytes
        self.structure_fields = [(self.prefix('hex'), self.array)]

    def pack(self, value):
        assert len(value) == self.num_bytes * 2
        return {self.prefix('hex'): self.array.from_buffer(
                bytearray.fromhex(value))}

    def unpack(self, data):
        return binascii.hexlify(getattr(data, self.prefix('hex')))


class ChoiceField(BaseStingyField):
    def __init__(self, choices):
        super(ChoiceField, self).__init__()
        self.choices = choices
        self.num_bits = len(bin(len(choices) - 1)[2:])

    def prepare_structure(self):
        self.structure_fields = [(self.prefix('cho'), ctypes.c_uint,
                                  self.num_bits)]

    def pack(self, value):
        return {self.prefix('cho'): self.choices.index(value)}

    def unpack(self, data):
        choice_index = getattr(data, self.prefix('cho'))
        return self.choices[choice_index]


class DateField(BaseStingyField):
    def prepare_structure(self):
        self.structure_fields = [(self.prefix('year'), ctypes.c_uint, 7),
                                 (self.prefix('month'), ctypes.c_uint, 4),
                                 (self.prefix('day'), ctypes.c_uint, 5)]

    def pack(self, value):
        assert type(value) is datetime.date, 'Wrong value!'

        return {self.prefix('year'): value.year - 2000,
                self.prefix('month'): value.month,
                self.prefix('day'): value.day}

    def unpack(self, data):
        year = getattr(data, self.prefix('year'))
        month = getattr(data, self.prefix('month'))
        day = getattr(data, self.prefix('day'))

        return datetime.date(2000 + year, month, day)


class StingyMeta(type):
    """This meta class is using for creating the Stingy class that have
    dynamicly named and ordered stingy fields"""
    @staticmethod
    def set_fields(klass, field_dict):
        klass.fields = []
        for name, field in field_dict.items():
            field.name = name
            field.prepare_structure()
            klass.fields.append(field)

    @staticmethod
    def sort_fields(klass):
        klass.fields = sorted(klass.fields, key=lambda x: x.order)

    def __new__(mcs, name, bases, attrs):
        klass = type.__new__(mcs, name, bases, attrs)
        stingy_field_dict = {k: v for k, v in attrs.items()
                             if isinstance(v, BaseStingyField)}

        mcs.set_fields(klass, stingy_field_dict)
        mcs.sort_fields(klass)

        return klass


class Stingy(object):
    __metaclass__ = StingyMeta
    fields = None

    def __init__(self):
        self._num_bytes = 0
        self._field_names = [field.name for field in self.fields]
        self._union = self._create_union()

    def _create_union(self):
        class StingyStructure(ctypes.BigEndianStructure):
            _fields_ = list(chain(*[field.structure_fields
                                    for field in self.fields]))

        self._num_bytes = ctypes.sizeof(StingyStructure)

        class StingyUnion(ctypes.Union):
            _fields_ = [("sub_fields", StingyStructure),
                        ("as_byte", ctypes.c_ubyte * self._num_bytes)]

        return StingyUnion()

    def _pack(self, data):
        for field in self.fields:
            value = data.get(field.name)
            field_dict = field.pack(value)
            for sub_field_name in field_dict:
                setattr(self._union.sub_fields,
                        sub_field_name,
                        field_dict[sub_field_name])

        return bytes(bytearray(self._union.as_byte))

    def _unpack(self, bytes):
        cbytearray = (ctypes.c_ubyte * self._num_bytes)
        byte_data = bytearray(bytes)
        self._union.as_byte = cbytearray(*byte_data)

        return {field.name: field.unpack(self._union.sub_fields)
                for field in self.fields}

    def b58encode(self, data):
        packed_data = self._pack(data)
        return base58.b58encode(packed_data)

    def b58decode(self, data):
        packed_data = base58.b58decode(data)
        return self._unpack(packed_data)

    def b64encode(self, data):
        packed_data = self._pack(data)
        return base64.b64encode(packed_data).rstrip('=')

    def b64decode(self, data):
        missing_pad = '=' * (4 - len(data) % 4)
        packed_data = base64.b64decode(data + missing_pad)
        return self._unpack(packed_data)
