# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/common.proto
"""Generated protocol buffer code."""
from google.protobuf.internal import builder as _builder
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x18proto/cloud/common.proto\x12\x0bproto.cloud\"\x07\n\x05\x45mpty\"\x1d\n\x05Point\x12\t\n\x01x\x18\x01 \x01(\x11\x12\t\n\x01y\x18\x02 \x01(\x11\"+\n\x04Pose\x12\t\n\x01x\x18\x01 \x01(\x11\x12\t\n\x01y\x18\x02 \x01(\x11\x12\r\n\x05theta\x18\x03 \x01(\x11\"F\n\x04Line\x12\x1e\n\x02p0\x18\x01 \x01(\x0b\x32\x12.proto.cloud.Point\x12\x1e\n\x02p1\x18\x02 \x01(\x0b\x32\x12.proto.cloud.Point\"\x8c\x01\n\nQuadrangle\x12\x1e\n\x02p0\x18\x01 \x01(\x0b\x32\x12.proto.cloud.Point\x12\x1e\n\x02p1\x18\x02 \x01(\x0b\x32\x12.proto.cloud.Point\x12\x1e\n\x02p2\x18\x03 \x01(\x0b\x32\x12.proto.cloud.Point\x12\x1e\n\x02p3\x18\x04 \x01(\x0b\x32\x12.proto.cloud.Point\"-\n\x07Polygon\x12\"\n\x06points\x18\x01 \x03(\x0b\x32\x12.proto.cloud.Point\"\x17\n\x06Switch\x12\r\n\x05value\x18\x01 \x01(\x08\"\x17\n\x06\x41\x63tive\x12\r\n\x05value\x18\x01 \x01(\x08\"\x1a\n\tNumerical\x12\r\n\x05value\x18\x01 \x01(\r\"f\n\x05\x46loor\x12%\n\x04type\x18\x01 \x01(\x0e\x32\x17.proto.cloud.Floor.Type\"6\n\x04Type\x12\n\n\x06UNKNOW\x10\x00\x12\x0b\n\x07\x42LANKET\x10\x01\x12\x08\n\x04WOOD\x10\x02\x12\x0b\n\x07\x43\x45RAMIC\x10\x03\"\xf4\x01\n\tRoomScene\x12)\n\x04type\x18\x01 \x01(\x0e\x32\x1b.proto.cloud.RoomScene.Type\x12+\n\x05index\x18\x02 \x01(\x0b\x32\x1c.proto.cloud.RoomScene.Index\x1a\x16\n\x05Index\x12\r\n\x05value\x18\x01 \x01(\r\"w\n\x04Type\x12\n\n\x06UNKNOW\x10\x00\x12\r\n\tSTUDYROOM\x10\x01\x12\x0b\n\x07\x42\x45\x44ROOM\x10\x02\x12\x0c\n\x08RESTROOM\x10\x03\x12\x0b\n\x07KITCHEN\x10\x04\x12\x0e\n\nLIVINGROOM\x10\x05\x12\x0e\n\nDININGROOM\x10\x06\x12\x0c\n\x08\x43ORRIDOR\x10\x07\x62\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.common_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _EMPTY._serialized_start=41
  _EMPTY._serialized_end=48
  _POINT._serialized_start=50
  _POINT._serialized_end=79
  _POSE._serialized_start=81
  _POSE._serialized_end=124
  _LINE._serialized_start=126
  _LINE._serialized_end=196
  _QUADRANGLE._serialized_start=199
  _QUADRANGLE._serialized_end=339
  _POLYGON._serialized_start=341
  _POLYGON._serialized_end=386
  _SWITCH._serialized_start=388
  _SWITCH._serialized_end=411
  _ACTIVE._serialized_start=413
  _ACTIVE._serialized_end=436
  _NUMERICAL._serialized_start=438
  _NUMERICAL._serialized_end=464
  _FLOOR._serialized_start=466
  _FLOOR._serialized_end=568
  _FLOOR_TYPE._serialized_start=514
  _FLOOR_TYPE._serialized_end=568
  _ROOMSCENE._serialized_start=571
  _ROOMSCENE._serialized_end=815
  _ROOMSCENE_INDEX._serialized_start=672
  _ROOMSCENE_INDEX._serialized_end=694
  _ROOMSCENE_TYPE._serialized_start=696
  _ROOMSCENE_TYPE._serialized_end=815
# @@protoc_insertion_point(module_scope)
