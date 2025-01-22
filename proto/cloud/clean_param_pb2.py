# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/clean_param.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from proto.cloud import common_pb2 as proto_dot_cloud_dot_common__pb2


DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x1dproto/cloud/clean_param.proto\x12\x0bproto.cloud\x1a\x18proto/cloud/common.proto\"v\n\x03\x46\x61n\x12)\n\x07suction\x18\x01 \x01(\x0e\x32\x18.proto.cloud.Fan.Suction\"D\n\x07Suction\x12\t\n\x05QUIET\x10\x00\x12\x0c\n\x08STANDARD\x10\x01\x12\t\n\x05TURBO\x10\x02\x12\x07\n\x03MAX\x10\x03\x12\x0c\n\x08MAX_PLUS\x10\x04\"\xb9\x01\n\x07MopMode\x12)\n\x05level\x18\x01 \x01(\x0e\x32\x1a.proto.cloud.MopMode.Level\x12\x36\n\x0c\x63orner_clean\x18\x02 \x01(\x0e\x32 .proto.cloud.MopMode.CornerClean\"&\n\x05Level\x12\x07\n\x03LOW\x10\x00\x12\n\n\x06MIDDLE\x10\x01\x12\x08\n\x04HIGH\x10\x02\"#\n\x0b\x43ornerClean\x12\n\n\x06NORMAL\x10\x00\x12\x08\n\x04\x44\x45\x45P\x10\x01\"u\n\x0b\x43leanCarpet\x12\x33\n\x08strategy\x18\x01 \x01(\x0e\x32!.proto.cloud.CleanCarpet.Strategy\"1\n\x08Strategy\x12\x0e\n\nAUTO_RAISE\x10\x00\x12\t\n\x05\x41VOID\x10\x01\x12\n\n\x06IGNORE\x10\x02\"\x86\x01\n\tCleanType\x12+\n\x05value\x18\x01 \x01(\x0e\x32\x1c.proto.cloud.CleanType.Value\"L\n\x05Value\x12\x0e\n\nSWEEP_ONLY\x10\x00\x12\x0c\n\x08MOP_ONLY\x10\x01\x12\x11\n\rSWEEP_AND_MOP\x10\x02\x12\x12\n\x0eSWEEP_THEN_MOP\x10\x03\"h\n\x0b\x43leanExtent\x12-\n\x05value\x18\x01 \x01(\x0e\x32\x1e.proto.cloud.CleanExtent.Value\"*\n\x05Value\x12\n\n\x06NORMAL\x10\x00\x12\n\n\x06NARROW\x10\x01\x12\t\n\x05QUICK\x10\x02\"J\n\nCleanTimes\x12\x12\n\nauto_clean\x18\x01 \x01(\r\x12\x14\n\x0cselect_rooms\x18\x02 \x01(\r\x12\x12\n\nspot_clean\x18\x04 \x01(\r\"\xa0\x02\n\nCleanParam\x12*\n\nclean_type\x18\x01 \x01(\x0b\x32\x16.proto.cloud.CleanType\x12.\n\x0c\x63lean_carpet\x18\x02 \x01(\x0b\x32\x18.proto.cloud.CleanCarpet\x12.\n\x0c\x63lean_extent\x18\x03 \x01(\x0b\x32\x18.proto.cloud.CleanExtent\x12&\n\x08mop_mode\x18\x04 \x01(\x0b\x32\x14.proto.cloud.MopMode\x12*\n\rsmart_mode_sw\x18\x05 \x01(\x0b\x32\x13.proto.cloud.Switch\x12\x1d\n\x03\x66\x61n\x18\x06 \x01(\x0b\x32\x10.proto.cloud.Fan\x12\x13\n\x0b\x63lean_times\x18\x07 \x01(\r\"t\n\x11\x43leanParamRequest\x12,\n\x0b\x63lean_param\x18\x01 \x01(\x0b\x32\x17.proto.cloud.CleanParam\x12\x31\n\x10\x61rea_clean_param\x18\x02 \x01(\x0b\x32\x17.proto.cloud.CleanParam\"\xd9\x01\n\x12\x43leanParamResponse\x12,\n\x0b\x63lean_param\x18\x01 \x01(\x0b\x32\x17.proto.cloud.CleanParam\x12,\n\x0b\x63lean_times\x18\x02 \x01(\x0b\x32\x17.proto.cloud.CleanTimes\x12\x31\n\x10\x61rea_clean_param\x18\x03 \x01(\x0b\x32\x17.proto.cloud.CleanParam\x12\x34\n\x13running_clean_param\x18\x04 \x01(\x0b\x32\x17.proto.cloud.CleanParamb\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.clean_param_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _FAN._serialized_start=72
  _FAN._serialized_end=190
  _FAN_SUCTION._serialized_start=122
  _FAN_SUCTION._serialized_end=190
  _MOPMODE._serialized_start=193
  _MOPMODE._serialized_end=378
  _MOPMODE_LEVEL._serialized_start=303
  _MOPMODE_LEVEL._serialized_end=341
  _MOPMODE_CORNERCLEAN._serialized_start=343
  _MOPMODE_CORNERCLEAN._serialized_end=378
  _CLEANCARPET._serialized_start=380
  _CLEANCARPET._serialized_end=497
  _CLEANCARPET_STRATEGY._serialized_start=448
  _CLEANCARPET_STRATEGY._serialized_end=497
  _CLEANTYPE._serialized_start=500
  _CLEANTYPE._serialized_end=634
  _CLEANTYPE_VALUE._serialized_start=558
  _CLEANTYPE_VALUE._serialized_end=634
  _CLEANEXTENT._serialized_start=636
  _CLEANEXTENT._serialized_end=740
  _CLEANEXTENT_VALUE._serialized_start=698
  _CLEANEXTENT_VALUE._serialized_end=740
  _CLEANTIMES._serialized_start=742
  _CLEANTIMES._serialized_end=816
  _CLEANPARAM._serialized_start=819
  _CLEANPARAM._serialized_end=1107
  _CLEANPARAMREQUEST._serialized_start=1109
  _CLEANPARAMREQUEST._serialized_end=1225
  _CLEANPARAMRESPONSE._serialized_start=1228
  _CLEANPARAMRESPONSE._serialized_end=1445
# @@protoc_insertion_point(module_scope)
