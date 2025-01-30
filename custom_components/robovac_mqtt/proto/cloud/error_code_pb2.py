# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/error_code.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from ...proto.cloud import common_pb2 as proto_dot_cloud_dot_common__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x1cproto/cloud/error_code.proto\x12\x0bproto.cloud\x1a\x18proto/cloud/common.proto\"A\n\x0c\x45rrorSetting\x12\x11\n\twarn_mask\x18\x01 \x03(\r\x12\x1e\n\x16obstacle_reminder_mask\x18\x02 \x03(\t\"\x9e\x04\n\tErrorCode\x12\x11\n\tlast_time\x18\x01 \x01(\x04\x12\r\n\x05\x65rror\x18\x02 \x03(\r\x12\x0c\n\x04warn\x18\x03 \x03(\r\x12*\n\x07setting\x18\x04 \x01(\x0b\x32\x19.proto.cloud.ErrorSetting\x12\x30\n\x08new_code\x18\n \x01(\x0b\x32\x1e.proto.cloud.ErrorCode.NewCode\x12/\n\x07\x62\x61ttery\x18\x0b \x01(\x0b\x32\x1e.proto.cloud.ErrorCode.Battery\x12\x42\n\x11obstacle_reminder\x18\x0c \x03(\x0b\x32\'.proto.cloud.ErrorCode.ObstacleReminder\x1a&\n\x07NewCode\x12\r\n\x05\x65rror\x18\x01 \x03(\r\x12\x0c\n\x04warn\x18\x02 \x03(\r\x1a\x1b\n\x07\x42\x61ttery\x12\x10\n\x08restored\x18\x01 \x01(\x08\x1a\xc8\x01\n\x10ObstacleReminder\x12:\n\x04type\x18\x01 \x01(\x0e\x32,.proto.cloud.ErrorCode.ObstacleReminder.Type\x12\x10\n\x08photo_id\x18\x02 \x01(\t\x12\x10\n\x08\x61\x63\x63uracy\x18\x03 \x01(\r\x12\x0e\n\x06map_id\x18\x04 \x01(\r\x12#\n\x05point\x18\x05 \x01(\x0b\x32\x12.proto.cloud.PointH\x00\"\x10\n\x04Type\x12\x08\n\x04POOP\x10\x00\x42\r\n\x0b\x44\x65scription\".\n\nPromptCode\x12\x11\n\tlast_time\x18\x01 \x01(\x04\x12\r\n\x05value\x18\x02 \x03(\rb\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.error_code_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _ERRORSETTING._serialized_start=71
  _ERRORSETTING._serialized_end=136
  _ERRORCODE._serialized_start=139
  _ERRORCODE._serialized_end=681
  _ERRORCODE_NEWCODE._serialized_start=411
  _ERRORCODE_NEWCODE._serialized_end=449
  _ERRORCODE_BATTERY._serialized_start=451
  _ERRORCODE_BATTERY._serialized_end=478
  _ERRORCODE_OBSTACLEREMINDER._serialized_start=481
  _ERRORCODE_OBSTACLEREMINDER._serialized_end=681
  _ERRORCODE_OBSTACLEREMINDER_TYPE._serialized_start=650
  _ERRORCODE_OBSTACLEREMINDER_TYPE._serialized_end=666
  _PROMPTCODE._serialized_start=683
  _PROMPTCODE._serialized_end=729
# @@protoc_insertion_point(module_scope)
