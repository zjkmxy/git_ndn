from ndn import encoding as enc


class SyncObject(enc.TlvModel):
    obj_type = enc.BytesField(0x01)
    obj_data = enc.BytesField(0x02)
