# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/version.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x19proto/cloud/version.proto\x12\x0bproto.cloud\"\xe9\x04\n\tProtoInfo\x12\x16\n\x0eglobal_verison\x18\x01 \x01(\r\x12\x33\n\x0c\x63ollect_dust\x18\x02 \x01(\x0b\x32\x1d.proto.cloud.ProtoInfo.Module\x12\x31\n\nmap_format\x18\x03 \x01(\x0b\x32\x1d.proto.cloud.ProtoInfo.Module\x12\x35\n\x0e\x63ontinue_clean\x18\x04 \x01(\x0b\x32\x1d.proto.cloud.ProtoInfo.Module\x12/\n\x08\x63ut_hair\x18\x05 \x01(\x0b\x32\x1d.proto.cloud.ProtoInfo.Module\x12-\n\x06timing\x18\x06 \x01(\x0b\x32\x1d.proto.cloud.ProtoInfo.Module\x1a*\n\x06Module\x12\x0f\n\x07version\x18\x01 \x01(\r\x12\x0f\n\x07options\x18\x02 \x01(\r\"2\n\x14\x43ollectDustOptionBit\x12\x1a\n\x16\x43OLLECT_DUST_APP_START\x10\x00\"c\n\x12MapFormatOptionBit\x12\x14\n\x10MAP_FORMAT_ANGLE\x10\x00\x12\x1a\n\x16MAP_FORMAT_RESERVE_MAP\x10\x01\x12\x1b\n\x17MAP_FORMAT_DEFAULT_NAME\x10\x02\"2\n\x16\x43ontinueCleanOptionBit\x12\x18\n\x14SMART_CONTINUE_CLEAN\x10\x00\"L\n\x0fTimingOptionBit\x12\x1f\n\x1bSCHEDULE_ROOMS_CLEAN_CUSTOM\x10\x00\x12\x18\n\x14SCHEDULE_SCENE_CLEAN\x10\x01\"\x81\x02\n\x0b\x41ppFunction\x12\x33\n\nmulti_maps\x18\x02 \x01(\x0b\x32\x1f.proto.cloud.AppFunction.Module\x12\x35\n\x0coptimization\x18\x03 \x01(\x0b\x32\x1f.proto.cloud.AppFunction.Module\x1a*\n\x06Module\x12\x0f\n\x07version\x18\x01 \x01(\r\x12\x0f\n\x07options\x18\x02 \x01(\r\"+\n\x14MultiMapsFunctionBit\x12\x13\n\x0fREMIND_MAP_SAVE\x10\x00\"-\n\x17OptimizationFunctionBit\x12\x12\n\x0ePATH_HIDE_TYPE\x10\x00*%\n\x06Global\x12\x08\n\x04NONE\x10\x00\x12\x11\n\rPROTO_VERSION\x10\x01\x62\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.version_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _GLOBAL._serialized_start=922
  _GLOBAL._serialized_end=959
  _PROTOINFO._serialized_start=43
  _PROTOINFO._serialized_end=660
  _PROTOINFO_MODULE._serialized_start=335
  _PROTOINFO_MODULE._serialized_end=377
  _PROTOINFO_COLLECTDUSTOPTIONBIT._serialized_start=379
  _PROTOINFO_COLLECTDUSTOPTIONBIT._serialized_end=429
  _PROTOINFO_MAPFORMATOPTIONBIT._serialized_start=431
  _PROTOINFO_MAPFORMATOPTIONBIT._serialized_end=530
  _PROTOINFO_CONTINUECLEANOPTIONBIT._serialized_start=532
  _PROTOINFO_CONTINUECLEANOPTIONBIT._serialized_end=582
  _PROTOINFO_TIMINGOPTIONBIT._serialized_start=584
  _PROTOINFO_TIMINGOPTIONBIT._serialized_end=660
  _APPFUNCTION._serialized_start=663
  _APPFUNCTION._serialized_end=920
  _APPFUNCTION_MODULE._serialized_start=335
  _APPFUNCTION_MODULE._serialized_end=377
  _APPFUNCTION_MULTIMAPSFUNCTIONBIT._serialized_start=830
  _APPFUNCTION_MULTIMAPSFUNCTIONBIT._serialized_end=873
  _APPFUNCTION_OPTIMIZATIONFUNCTIONBIT._serialized_start=875
  _APPFUNCTION_OPTIMIZATIONFUNCTIONBIT._serialized_end=920
# @@protoc_insertion_point(module_scope)
