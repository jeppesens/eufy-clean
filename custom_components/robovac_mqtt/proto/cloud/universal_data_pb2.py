# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/universal_data.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from ...proto.cloud import common_pb2 as proto_dot_cloud_dot_common__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n proto/cloud/universal_data.proto\x12\x0bproto.cloud\x1a\x18proto/cloud/common.proto\"\x16\n\x14UniversalDataRequest\"\x83\x02\n\x15UniversalDataResponse\x12\x42\n\x0c\x63ur_map_room\x18\x01 \x01(\x0b\x32,.proto.cloud.UniversalDataResponse.RoomTable\x1a\xa5\x01\n\tRoomTable\x12\x0e\n\x06map_id\x18\x01 \x01(\r\x12?\n\x04\x64\x61ta\x18\x02 \x03(\x0b\x32\x31.proto.cloud.UniversalDataResponse.RoomTable.Data\x1aG\n\x04\x44\x61ta\x12\n\n\x02id\x18\x01 \x01(\r\x12\x0c\n\x04name\x18\x02 \x01(\t\x12%\n\x05scene\x18\x03 \x01(\x0b\x32\x16.proto.cloud.RoomSceneb\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.universal_data_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _UNIVERSALDATAREQUEST._serialized_start=75
  _UNIVERSALDATAREQUEST._serialized_end=97
  _UNIVERSALDATARESPONSE._serialized_start=100
  _UNIVERSALDATARESPONSE._serialized_end=359
  _UNIVERSALDATARESPONSE_ROOMTABLE._serialized_start=194
  _UNIVERSALDATARESPONSE_ROOMTABLE._serialized_end=359
  _UNIVERSALDATARESPONSE_ROOMTABLE_DATA._serialized_start=288
  _UNIVERSALDATARESPONSE_ROOMTABLE_DATA._serialized_end=359
# @@protoc_insertion_point(module_scope)
