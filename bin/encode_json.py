import os
import sys
from dotenv import load_dotenv
import ndn.security as sec
import gitsync.db.proto as proto
import gitsync.db.json_encoder as json_encoder


def main():
    load_dotenv()
    if len(sys.argv) <= 1:
        print(f'Usage: {sys.argv[0]} <filename>', file=sys.stderr)
        exit(-1)

    filename = os.path.abspath(sys.argv[1])
    tpm = sec.TpmFile(os.path.abspath(os.getenv('GIT_NDN_TPM')))
    signer = tpm.get_signer(os.getenv('GIT_NDN_KEY'))

    with open(filename, 'r') as f:
        content = f.read()
    git_obj = json_encoder.json_decode(content)
    wire = proto.encode(git_obj, signer)

    file_prefix, _ = os.path.splitext(filename)
    tlv_filename = file_prefix + '.tlv'
    with open(tlv_filename, 'wb') as f:
        f.write(wire)


if __name__ == '__main__':
    main()
