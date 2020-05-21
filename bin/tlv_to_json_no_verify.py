import os
import sys
import gitsync.db.json_encoder as json_encoder
import gitsync.db.proto as proto


def main():
    if len(sys.argv) <= 1:
        print(f'Usage: {sys.argv[0]} <filename>', file=sys.stderr)
        exit(-1)
    filename = sys.argv[1]
    if not os.path.exists(filename):
        print(f'File does not exist: {filename}', file=sys.stderr)
        exit(-2)

    with open(filename, 'rb') as f:
        content = f.read()
        obj, _ = proto.parse_gitobj(content)
        print(json_encoder.json_encode(obj), file=sys.stdout)


if __name__ == '__main__':
    main()
