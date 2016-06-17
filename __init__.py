import binascii
import ctypes
import datetime
from itertools import chain


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
        self.num_bits = num_bits or max_value.bit_length()

    def prepare_structure(self):
        type_ = ctypes.c_uint if self.num_bits <= 32 else ctypes.c_ulonglong
        self.structure_fields = [(self.prefix('num'), type_, self.num_bits)]

    def pack(self, value):
        assert value.bit_length() <= self.num_bits
        return {self.prefix('num'): value}

    def unpack(self, data):
        return int(getattr(data, self.prefix('num')))


class BooleanField(BaseStingyField):
    def __init__(self):
        super(BooleanField, self).__init__()
        self.num_bits = 1

    def prepare_structure(self):
        self.structure_fields = [(self.prefix('bool'), ctypes.c_ubyte,
                                  self.num_bits)]

    def pack(self, value):
        assert type(value) is bool
        return {self.prefix('bool'): value}

    def unpack(self, data):
        return bool(getattr(data, self.prefix('bool')))


class HexField(BaseStingyField):
    def __init__(self, length):
        assert length % 2 == 0, 'Hex value length should be a multiple of 2'
        super(HexField, self).__init__()
        self.num_bytes = length / 2
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
        self.num_bits = len(choices).bit_length()

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


class ListField(BaseStingyField):
    def __init__(self, field, length, **kwargs):
        super(ListField, self).__init__()
        self.field_class = field
        self.length = length
        self.fields = []
        self.field_kwargs = kwargs

    def prepare_structure(self):
        self.structure_fields = [(self.prefix('size'), ctypes.c_uint,
                                  self.length.bit_length())]
        # fill in the fields with field instances
        for i in range(self.length):
            field = self.field_class(**self.field_kwargs)
            field.name = self.prefix(i)
            field.prepare_structure()
            self.fields.append(field)
        # set list of structures
        self.structure_fields += list(chain(*[field.structure_fields
                                              for field in self.fields]))

    def pack(self, values):
        result = {self.prefix('size'): len(values)}
        for field, value in zip(self.fields, values):
            result.update(field.pack(value))
        return result

    def unpack(self, data):
        size = getattr(data, self.prefix('size'))
        result = []
        for field in self.fields[:size]:
            result.append(field.unpack(data))
        return result


class MultipleChoiceField(BaseStingyField):
    def __init__(self, choices):
        super(MultipleChoiceField, self).__init__()
        self.choices = choices
        self.num_bits = len(choices)

    def prepare_structure(self):
        self.structure_fields = [(self.prefix('mcho'), ctypes.c_uint,
                                  self.num_bits)]

    def pack(self, value):
        binary_ids = set(map(self.choices.index, value))
        decimal_sum = sum([2 ** id for id in binary_ids])
        return {self.prefix('mcho'): decimal_sum}

    def unpack(self, data):
        choices_sum = getattr(data, self.prefix('mcho'))

        values = set()
        for i, choice in reversed(list(enumerate(self.choices))):
            binary_index = 2 ** i
            if binary_index <= choices_sum:
                values.add(choice)
                choices_sum -= binary_index
                if choices_sum == 0:
                    break
        return values


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
    VERSION = None  # to be filled by the child encoder class

    def __init__(self):
        self._num_bytes = 0
        self._field_names = [field.name for field in self.fields]
        self._union = self._create_union()
        self.cache = {}

    def _create_union(self):
        class StingyStructure(ctypes.BigEndianStructure):
            _fields_ = list(chain(*[field.structure_fields
                            for field in self.fields]))

        self._num_bytes = ctypes.sizeof(StingyStructure)

        class StingyUnion(ctypes.Union):
            _fields_ = [("sub_fields", StingyStructure),
                        ("as_byte", ctypes.c_ubyte * self._num_bytes)]

        return StingyUnion()

    @staticmethod
    def get_version(byte_string):
        return ord(byte_string[-1])

    def encode(self, data):
        """
        first we use the "pack" method of every field to get all the
        data in a dictionary format.

        then we iterate over the dictionary to put every subfield to the
        union with setattr method
        """
        # reset all the fields
        self._union.as_bytes = (ctypes.c_ubyte * self._num_bytes)(0)

        # bind subfields name to prevent calling it in a tight loop
        subfields = self._union.sub_fields

        for field in self.fields:
            field_value = data.get(field.name)
            key = field.name + str(field_value)
            if key in self.cache:
                field_dict = self.cache[key]
            else:
                field_dict = field.pack(field_value)
                self.cache[key] = field_dict
            for sub_field_name in field_dict:
                setattr(subfields,
                        sub_field_name,
                        field_dict[sub_field_name])
        b_array = bytearray(self._union.as_byte)
        b_array.append(self.VERSION)
        return bytes(b_array)

    def decode(self, byte_string):
        cbytearray = (ctypes.c_ubyte * self._num_bytes)
        byte_data = bytearray(byte_string)
        # remove version info
        byte_data.pop()
        self._union.as_byte = cbytearray(*byte_data)

        return {field.name: field.unpack(self._union.sub_fields)
                for field in self.fields}
