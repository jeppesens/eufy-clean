# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/undisturbed.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from proto.cloud import common_pb2 as proto_dot_cloud_dot_common__pb2


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x1dproto/cloud/undisturbed.proto\x12\x0bproto.cloud\x1a\x18proto/cloud/common.proto\"\xbd\x01\n\x0bUndisturbed\x12\x1f\n\x02sw\x18\x01 \x01(\x0b\x32\x13.proto.cloud.Switch\x12\x31\n\x05\x62\x65gin\x18\x02 \x01(\x0b\x32\".proto.cloud.Undisturbed.TimePoint\x12/\n\x03\x65nd\x18\x03 \x01(\x0b\x32\".proto.cloud.Undisturbed.TimePoint\x1a)\n\tTimePoint\x12\x0c\n\x04hour\x18\x01 \x01(\r\x12\x0e\n\x06minute\x18\x02 \x01(\r\"C\n\x12UndisturbedRequest\x12-\n\x0bundisturbed\x18\x01 \x01(\x0b\x32\x18.proto.cloud.Undisturbed\"i\n\x13UndisturbedResponse\x12#\n\x06\x61\x63tive\x18\x01 \x01(\x0b\x32\x13.proto.cloud.Active\x12-\n\x0bundisturbed\x18\x02 \x01(\x0b\x32\x18.proto.cloud.Undisturbedb\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.undisturbed_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _UNDISTURBED._serialized_start=73
  _UNDISTURBED._serialized_end=262
  _UNDISTURBED_TIMEPOINT._serialized_start=221
  _UNDISTURBED_TIMEPOINT._serialized_end=262
  _UNDISTURBEDREQUEST._serialized_start=264
  _UNDISTURBEDREQUEST._serialized_end=331
  _UNDISTURBEDRESPONSE._serialized_start=333
  _UNDISTURBEDRESPONSE._serialized_end=438
# @@protoc_insertion_point(module_scope)
