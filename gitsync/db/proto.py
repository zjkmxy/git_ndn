from typing import Optional, Tuple
from ndn.encoding import TlvModel, BytesField, UintField, RepeatedField, ModelField, BoolField,\
    ProcedureArgument, OffsetMarker, SignatureInfo, BinaryStr, Signer, SignaturePtrs
from ndn.encoding.tlv_model import SignatureValueField


class OperationRule(TlvModel):
    operation = UintField(0x9c)
    access = UintField(0x9d)
    user_id = BytesField(0x81)
    group_id = BytesField(0x82)


class LabelRule(TlvModel):
    label = BytesField(0x98)
    min_value = UintField(0x9e, fixed_len=1)
    max_value = UintField(0x9f, fixed_len=1)
    user_id = BytesField(0x81)
    group_id = BytesField(0x82)


class RefConfig(TlvModel):
    ref_name = BytesField(0x95)
    operation_rules = RepeatedField(ModelField(0x96, OperationRule))
    label_rules = RepeatedField(ModelField(0x97, LabelRule))


class LabelValue(TlvModel):
    value = UintField(0xa0, fixed_len=1)
    description = BytesField(0xa1)


class LabelConfig(TlvModel):
    label = BytesField(0x98)
    function = UintField(0x99)
    default_value = UintField(0x9a)
    values = RepeatedField(ModelField(0x9b, LabelValue))


class ProjectConfig(TlvModel):
    project_id = BytesField(0x80)
    description = BytesField(0x90)
    inherit_from = BytesField(0x91)
    sync_interval = UintField(0x92)
    ref_configs = RepeatedField(ModelField(0x93, RefConfig))
    labels = RepeatedField(ModelField(0x94, LabelConfig))


class AccountConfig(TlvModel):
    user_id = BytesField(0x81)
    full_name = BytesField(0xa2)
    email = BytesField(0xa3)


class KeyRevocation(TlvModel):
    key_id = BytesField(0x83)
    revoke_time = BytesField(0xa4)
    # current_heads = RepeatedField(BytesField(0xa5))


class GroupConfig(TlvModel):
    group_id = BytesField(0x82)
    full_name = BytesField(0xa2)
    owner = BytesField(0xa3)
    members = BytesField(0xa4)


class HeadRef(TlvModel):
    head = BytesField(0x84)
    change_id = BytesField(0x85)
    change_id_meta_commit = BytesField(0xa5)


class ChangeMeta(TlvModel):
    change_id = BytesField(0x85)
    status = UintField(0xa6)
    patch_set = UintField(0x86)
    subject = BytesField(0xa7)


class Vote(TlvModel):
    label = BytesField(0x98)
    value = UintField(0xa0, fixed_len=1)


class Comment(TlvModel):
    comment_id = BytesField(0x87)
    filename = BytesField(0xa8)
    line_nbr = UintField(0xa9)
    author = BytesField(0xaa)
    written_on = BytesField(0xab)
    message = BytesField(0xac)
    rev_id = BytesField(0xad)
    unsolved = BoolField(0xae)


class Catalog(TlvModel):
    entries = RepeatedField(BytesField(0xaf))


class GitObject(TlvModel):
    _signer = ProcedureArgument()
    _sig_cover_part = ProcedureArgument()
    _sig_value_buf = ProcedureArgument()
    _shrink_len = ProcedureArgument(0)

    _sig_cover_start = OffsetMarker()
    project_config = ModelField(0xf0, ProjectConfig)
    account_config = ModelField(0xf1, AccountConfig)
    key_revocation = ModelField(0xf2, KeyRevocation)
    group_config = ModelField(0xf3, GroupConfig)
    head_ref = ModelField(0xf4, HeadRef)
    change_meta = ModelField(0xf5, ChangeMeta)
    vote = ModelField(0xf6, Vote)
    comment = ModelField(0xf7, Comment)
    catalog = ModelField(0xf8, Catalog)

    signature_info = ModelField(0xe0, SignatureInfo)
    signature_value = SignatureValueField(0xe1,
                                          signer=_signer,
                                          covered_part=_sig_cover_part,
                                          starting_point=_sig_cover_start,
                                          value_buffer=_sig_value_buf,
                                          shrink_len=_shrink_len)


def encode(obj: TlvModel, signer: Optional[Signer] = None) -> bytes:
    git_obj = GitObject()
    if isinstance(obj, ProjectConfig):
        git_obj.project_config = obj
    elif isinstance(obj, AccountConfig):
        git_obj.account_config = obj
    elif isinstance(obj, KeyRevocation):
        git_obj.key_revocation = obj
    elif isinstance(obj, GroupConfig):
        git_obj.group_config = obj
    elif isinstance(obj, HeadRef):
        git_obj.head_ref = obj
    elif isinstance(obj, ChangeMeta):
        git_obj.change_meta = obj
    elif isinstance(obj, Vote):
        git_obj.vote = obj
    elif isinstance(obj, Comment):
        git_obj.comment = obj
    elif isinstance(obj, Catalog):
        git_obj.catalog = obj
    else:
        raise ValueError(f'Unrecognized object: {obj}')

    if signer is not None:
        git_obj.signature_info = SignatureInfo()
    markers = {}
    git_obj._signer.set_arg(markers, signer)
    ret = git_obj.encode(markers=markers)
    GitObject.signature_value.calculate_signature(markers)
    shrink_size = git_obj._shrink_len.get_arg(markers)
    return bytes(ret[:-shrink_size])


def parse(wire: BinaryStr) -> Tuple[TlvModel, SignaturePtrs]:
    markers = {}
    git_obj = GitObject.parse(wire, {}, ignore_critical=True)
    sig_ptrs = SignaturePtrs(
        signature_info=git_obj.signature_info,
        signature_covered_part=git_obj._sig_cover_part.get_arg(markers),
        signature_value_buf=git_obj.signature_value,
    )

    if git_obj.project_config is not None:
        ret = git_obj.project_config
    elif git_obj.account_config is not None:
        ret = git_obj.account_config
    elif git_obj.key_revocation is not None:
        ret = git_obj.key_revocation
    elif git_obj.group_config is not None:
        ret = git_obj.group_config
    elif git_obj.head_ref is not None:
        ret = git_obj.head_ref
    elif git_obj.change_meta is not None:
        ret = git_obj.change_meta
    elif git_obj.vote is not None:
        ret = git_obj.vote
    elif git_obj.comment is not None:
        ret = git_obj.comment
    elif git_obj.catalog is not None:
        ret = git_obj.catalog
    else:
        raise ValueError(f'The object parsed is empty')

    return ret, sig_ptrs
