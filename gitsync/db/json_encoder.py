import json
import ndn.encoding as encoding
from . import proto


class GitObjectEncoder(json.JSONEncoder):
    def _encode_field(self, field, val):
        if isinstance(val, list) and val == []:
            return None
        if val is None:
            return None

        if isinstance(field, encoding.ModelField):
            return self.default(val)
        elif isinstance(field, encoding.UintField):
            if field.name in ['value', 'min_value', 'max_value', 'default_value']:
                return val - 128
            else:
                return val
        elif isinstance(field, encoding.BoolField):
            return val
        elif isinstance(field, encoding.NameField):
            return encoding.Name.to_str(val)
        elif isinstance(field, encoding.BytesField):
            if field.name == 'key_id':
                return val.hex()
            else:
                return val.decode('utf-8')
        elif isinstance(field, encoding.RepeatedField):
            lst = [self._encode_field(field.element_type, cur) for cur in val]
            return list(x for x in lst if x is not None and x != [])
        elif isinstance(field, encoding.ProcedureArgument):
            return None
        else:
            raise TypeError(f"Field of type {field.__class__.__name__} is not JSON serializable")

    def default(self, obj):
        if isinstance(obj, proto.GitObject):
            typ = None
            val = None
            for field in obj._encoded_fields:
                if isinstance(field, encoding.ModelField):
                    val = field.get_value(obj)
                    if val is not None:
                        typ = field.name
                        break
            if not typ:
                return None
            else:
                return {
                    'object_type': typ,
                    'value': self.default(val)
                }
        elif isinstance(obj, encoding.TlvModel):
            ret = {}
            for field in obj._encoded_fields:
                val = self._encode_field(field, field.get_value(obj))
                if val is not None:
                    ret[field.name] = val
            return ret
        else:
            return super(self).default(obj)


def json_encode(obj: proto.GitObject) -> str:
    return json.dumps(obj, indent=2, cls=GitObjectEncoder)


def json_decode(text: str) -> proto.GitObject:
    pass
