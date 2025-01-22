import base64
import time

from google.protobuf import descriptor_pool, message_factory, text_format
from google.protobuf.descriptor_pb2 import FileDescriptorSet


async def sleep(ms: int):
    time.sleep(ms / 1000)


def get_proto_file(proto_file_path: str):
    with open(proto_file_path, "rb") as f:
        file_descriptor_set = FileDescriptorSet()
        file_descriptor_set.ParseFromString(f.read())

    pool = descriptor_pool.DescriptorPool()
    for file_descriptor_proto in file_descriptor_set.file:
        pool.Add(file_descriptor_proto)
    return pool


def decode(pool: str, message_type, base64_value):
    pool = get_proto_file(pool)
    factory = message_factory.MessageFactory(pool)
    message_descriptor = pool.FindMessageTypeByName(message_type)
    message_class = factory.GetPrototype(message_descriptor)
    message = message_class()

    binary_data = base64.b64decode(base64_value)
    message.ParseFromString(binary_data)
    return message


async def encode(proto, type, obj):
    factory = get_proto_file(proto)
    proto_lookup_type = factory.GetPrototype(factory.pool.FindMessageTypeByName(type))
    message = proto_lookup_type(**obj)
    buffer = message.SerializeToString()
    return base64.b64encode(buffer).decode('utf-8')


async def get_flat_data(proto, type, number):
    factory = get_proto_file(proto)
    proto_lookup_type = factory.pool.FindMessageTypeByName(type)
    decoded_message = get_key_by_value(proto_lookup_type, number)
    return decoded_message


async def get_multi_data(proto, type, base64_value):
    factory = get_proto_file(proto)
    proto_lookup_type = factory.GetPrototype(factory.pool.FindMessageTypeByName(type))
    buffer = base64.b64decode(base64_value)
    values = []

    if proto_lookup_type.DESCRIPTOR.fields:
        field_keys = [field.message_type.name for field in proto_lookup_type.DESCRIPTOR.fields]

        for field_key in field_keys:
            try:
                field = factory.GetPrototype(factory.pool.FindMessageTypeByName(field_key))
                decoded_message = field.FromString(buffer)
                decoded_object = text_format.MessageToDict(decoded_message)
                values.append({'key': field_key, **decoded_object})
            except Exception:
                pass

    return values


def get_key_by_value(obj, value):
    for key, val in obj.items():
        if val == value:
            return key
    return None
