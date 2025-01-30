# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: proto/cloud/p2pdata.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()


from ...proto.cloud import common_pb2 as proto_dot_cloud_dot_common__pb2
from ...proto.cloud import stream_pb2 as proto_dot_cloud_dot_stream__pb2

DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\x19proto/cloud/p2pdata.proto\x12\x0fproto.cloud.p2p\x1a\x18proto/cloud/common.proto\x1a\x18proto/cloud/stream.proto\"\xcd\x01\n\rMapChannelMsg\x12\x34\n\x04type\x18\x01 \x01(\x0e\x32&.proto.cloud.p2p.MapChannelMsg.MsgType\x12,\n\x08map_info\x18\x02 \x01(\x0b\x32\x18.proto.cloud.p2p.MapInfoH\x00\x12\x1c\n\x12multi_map_response\x18\x03 \x01(\x0cH\x00\"/\n\x07MsgType\x12\x0c\n\x08MAP_INFO\x10\x00\x12\x16\n\x12MULTI_MAP_RESPONSE\x10\x01\x42\t\n\x07MsgData\"/\n\tMapPixels\x12\x0e\n\x06pixels\x18\x01 \x01(\x0c\x12\x12\n\npixel_size\x18\x02 \x01(\r\"\xf2\x05\n\x07MapInfo\x12\x10\n\x08releases\x18\x01 \x01(\r\x12\x0e\n\x06map_id\x18\x02 \x01(\r\x12\x12\n\nmap_stable\x18\x03 \x01(\x08\x12\x11\n\tmap_width\x18\x04 \x01(\r\x12\x12\n\nmap_height\x18\x05 \x01(\r\x12\"\n\x06origin\x18\x06 \x01(\x0b\x32\x12.proto.cloud.Point\x12 \n\x05\x64ocks\x18\x07 \x03(\x0b\x32\x11.proto.cloud.Pose\x12\x35\n\x08msg_type\x18\x08 \x01(\x0e\x32#.proto.cloud.p2p.MapInfo.MapMsgType\x12,\n\x06pixels\x18\t \x01(\x0b\x32\x1a.proto.cloud.p2p.MapPixelsH\x00\x12\x35\n\tobstacles\x18\n \x01(\x0b\x32 .proto.cloud.stream.ObstacleInfoH\x00\x12>\n\x10restricted_zones\x18\x0b \x01(\x0b\x32\".proto.cloud.stream.RestrictedZoneH\x00\x12\x35\n\x0broom_params\x18\x0c \x01(\x0b\x32\x1e.proto.cloud.stream.RoomParamsH\x00\x12\x35\n\x0b\x63ruise_data\x18\r \x01(\x0b\x32\x1e.proto.cloud.stream.CruiseDataH\x00\x12;\n\x0etemporary_data\x18\x0e \x01(\x0b\x32!.proto.cloud.stream.TemporaryDataH\x00\x12\x12\n\nis_new_map\x18\x0f \x01(\r\x12\x0c\n\x04name\x18\x10 \x01(\t\"\x90\x01\n\nMapMsgType\x12\x10\n\x0cMAP_REALTIME\x10\x00\x12\x13\n\x0fMAP_ROOMOUTLINE\x10\x01\x12\x11\n\rOBSTACLE_INFO\x10\x02\x12\x12\n\x0eRESTRICT_ZONES\x10\x03\x12\x0f\n\x0bROOM_PARAMS\x10\x04\x12\x0f\n\x0b\x43RUISE_DATA\x10\x05\x12\x12\n\x0eTEMPORARY_DATA\x10\x06\x42\x08\n\x06MapMsg\"\x90\x04\n\x0b\x43ompleteMap\x12\x10\n\x08releases\x18\x01 \x01(\r\x12\x0e\n\x06map_id\x18\x02 \x01(\r\x12\x12\n\nmap_stable\x18\x03 \x01(\x08\x12\x11\n\tmap_width\x18\x04 \x01(\r\x12\x12\n\nmap_height\x18\x05 \x01(\r\x12\"\n\x06origin\x18\x06 \x01(\x0b\x32\x12.proto.cloud.Point\x12 \n\x05\x64ocks\x18\x07 \x03(\x0b\x32\x11.proto.cloud.Pose\x12\'\n\x03map\x18\x08 \x01(\x0b\x32\x1a.proto.cloud.p2p.MapPixels\x12\x30\n\x0croom_outline\x18\t \x01(\x0b\x32\x1a.proto.cloud.p2p.MapPixels\x12\x33\n\tobstacles\x18\n \x01(\x0b\x32 .proto.cloud.stream.ObstacleInfo\x12<\n\x10restricted_zones\x18\x0b \x01(\x0b\x32\".proto.cloud.stream.RestrictedZone\x12\x33\n\x0broom_params\x18\x0c \x01(\x0b\x32\x1e.proto.cloud.stream.RoomParams\x12\x39\n\x0etemporary_data\x18\r \x01(\x0b\x32!.proto.cloud.stream.TemporaryData\x12\x12\n\nis_new_map\x18\x0e \x01(\r\x12\x0c\n\x04name\x18\x0f \x01(\t\"\x90\x01\n\x0c\x43ompletePath\x12\x0c\n\x04path\x18\x03 \x01(\x0c\x12\x13\n\x0bpath_lz4len\x18\x04 \x01(\r\"?\n\x04Type\x12\t\n\x05SWEEP\x10\x00\x12\x07\n\x03MOP\x10\x01\x12\r\n\tSWEEP_MOP\x10\x02\x12\x08\n\x04NAVI\x10\x03\x12\n\n\x06GOHOME\x10\x04\"\x1c\n\x05State\x12\n\n\x06\x46OLLOW\x10\x00\x12\x07\n\x03NEW\x10\x01\x62\x06proto3')

_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, globals())
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'proto.cloud.p2pdata_pb2', globals())
if _descriptor._USE_C_DESCRIPTORS == False:

  DESCRIPTOR._options = None
  _MAPCHANNELMSG._serialized_start=99
  _MAPCHANNELMSG._serialized_end=304
  _MAPCHANNELMSG_MSGTYPE._serialized_start=246
  _MAPCHANNELMSG_MSGTYPE._serialized_end=293
  _MAPPIXELS._serialized_start=306
  _MAPPIXELS._serialized_end=353
  _MAPINFO._serialized_start=356
  _MAPINFO._serialized_end=1110
  _MAPINFO_MAPMSGTYPE._serialized_start=956
  _MAPINFO_MAPMSGTYPE._serialized_end=1100
  _COMPLETEMAP._serialized_start=1113
  _COMPLETEMAP._serialized_end=1641
  _COMPLETEPATH._serialized_start=1644
  _COMPLETEPATH._serialized_end=1788
  _COMPLETEPATH_TYPE._serialized_start=1695
  _COMPLETEPATH_TYPE._serialized_end=1758
  _COMPLETEPATH_STATE._serialized_start=1760
  _COMPLETEPATH_STATE._serialized_end=1788
# @@protoc_insertion_point(module_scope)
