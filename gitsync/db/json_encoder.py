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


class GitObjectDecoder(json.JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self._object_hook, *args, **kwargs)

    def _decode_field(self, field_name: str, val):
        # decode a dict into a single TLV field top-down
        if isinstance(val, bool):
            return val
        elif isinstance(val, int):
            if field_name in ['value', 'min_value', 'max_value', 'default_value']:
                return val + 128
            else:
                return val
        elif isinstance(val, str):
            if field_name == 'key_id':
                return bytes.fromhex(val)
            else:
                return val.encode('utf-8')
        elif isinstance(val, list):
            return list(self._decode_field(None, x) for x in val)
    
    def _decode_model(self, modelType: type, dct):
        ret = modelType()
        for field in ret._encoded_fields:
            if field.name in dct:
                setattr(ret, field.name, self._decode_field(field.name, dct[field.name]))
        return ret

    def _object_hook(self, dct):
        # if has object_type field, construct GitObject
        if 'object_type' in dct:
            typ = None
            object_type = dct['object_type']
            if object_type == 'project_config':
                typ = proto.ProjectConfig
            elif object_type == 'account_config':
                typ = proto.AccountConfig
            elif object_type == 'key_revocation':
                typ = proto.KeyRevocation
            elif object_type == 'group_config':
                typ = proto.GroupConfig
            elif object_type == 'head_ref':
                typ = proto.HeadRef
            elif object_type == 'change_meta':
                typ = proto.ChangeMeta
            elif object_type == 'vote':
                typ = proto.Vote
            elif object_type == 'comment':
                typ = proto.Comment
            elif object_type == 'catalog':
                typ = proto.Catalog
            ret = proto.GitObject()
            setattr(ret, object_type, self._decode_model(typ, dct['value']))
            return ret
        else:
            return dct


def json_encode(obj: proto.GitObject) -> str:
    return json.dumps(obj, indent=2, cls=GitObjectEncoder)


def json_decode(text: str) -> proto.GitObject:
    return json.loads(text, cls=GitObjectDecoder)