from ndn import encoding as enc


class SyncObject(enc.TlvModel):
    obj_type = enc.BytesField(0x01)
    obj_data = enc.BytesField(0x02)


class RefInfo(enc.TlvModel):
    ref_name = enc.BytesField(0x03)
    ref_head = enc.BytesField(0x04)


class SyncUpdate(enc.TlvModel):
    ref_into = enc.RepeatedField(enc.ModelField(0x05, RefInfo))


class PushRequest(enc.TlvModel):
    ret_info = enc.ModelField(0x05, RefInfo)
    force = enc.BoolField(0x06)


class AddUserReq(enc.TlvModel):
    full_name = enc.BytesField(0x07)
    email = enc.BytesField(0x08)
    cert = enc.BytesField(0x09)
