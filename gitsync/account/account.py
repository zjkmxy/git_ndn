import logging
import ndn.encoding as enc
from Cryptodome.PublicKey import ECC, RSA
from Cryptodome.Signature import DSS, pkcs1_15
from Cryptodome.Hash import SHA256
from .. import repos


class Accounts:
    repos: repos.GitRepos

    def __init__(self, git_repos):
        self.repos = git_repos

    def verify(self, sig_ptrs: enc.SignaturePtrs) -> bool:
        if (sig_ptrs.signature_info is None
                or sig_ptrs.signature_info.key_locator is None
                or sig_ptrs.signature_info.key_locator.name is None):
            logging.info(f'No signature')
            return False
        user_name = bytes(enc.Component.get_value(sig_ptrs.signature_info.key_locator.name[-3])).decode()
        key_name = bytes(enc.Component.get_value(sig_ptrs.signature_info.key_locator.name[-1])).hex()

        try:
            cert = self.repos.read_file('All-Users.git',
                                        f'refs/users/{user_name[:2]}/{user_name}',
                                        f'KEY/{key_name}.cert')
        except KeyError as e:
            if e.args[0] == 0:
                logging.warning(f'Repo All-Users.git does not exist')
            if e.args[0] == 1:
                logging.warning(f'User {user_name} does not exist')
            elif e.args[0] == 2:
                logging.warning(f'Certificate {user_name}/KEY/{key_name}.cert does not exist')
            return False

        try:
            _, _, key_bits, _ = enc.parse_data(cert, with_tl=True)
            pub_key = ECC.import_key(bytes(key_bits))
            verifier = DSS.new(pub_key, 'fips-186-3', 'der')
        except (ValueError, IndexError, KeyError):
            logging.warning(f'Certificate {user_name}/KEY/{key_name}.cert is malformed')
            return False

        h = SHA256.new()
        for content in sig_ptrs.signature_covered_part:
            h.update(content)
        try:
            verifier.verify(h, bytes(sig_ptrs.signature_value_buf))
        except ValueError:
            logging.info(f'Unable to verify the signature: signed by {user_name}/KEY/{key_name}')
            return False
        logging.debug(f'Verification passed')
        return True
