import base64

from proto.cloud.control_pb2 import ModeCtrlResponse

"""js
/**
  * this works in nodejs
  */
import { decode } from './lib/utils';
const val = 'AggB';

decode('./proto/cloud/control.proto', 'ModeCtrlResponse', val)
    .then(value => {
        console.log(value);
    });
"""

# this does not work in python
val = 'AggB'
m = ModeCtrlResponse()
v = base64.b64decode(val)
m.MergeFromString(v)
print(m)
