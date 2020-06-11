import os
import logging
import ndn.encoding as enc
from Cryptodome.PublicKey import ECC, RSA
from Cryptodome.Signature import DSS, pkcs1_15
from Cryptodome.Hash import SHA256
from .. import repos


class Accounts:
    repos: repos.GitRepos

    def __init__(self, git_repos):
        self.repo = git_repos['All-Users.git']
        self.trust_anchor_verifier = None
        self.trust_anchor_name = None

    def read_trust_anchor(self):
        ta_path = os.path.abspath(os.getenv('GIT_NDN_TRUST_ANCHOR'))
        with open(ta_path, 'rb') as f:
            cert = f.read()
        ta_name, _, key_bits, _ = enc.parse_data(cert, with_tl=True)
        user_name = bytes(enc.Component.get_value(ta_name[-5])).decode()
        key_name = bytes(enc.Component.get_value(ta_name[-3])).hex()
        self.trust_anchor_name = (user_name, key_name)
        pub_key = ECC.import_key(bytes(key_bits))
        self.trust_anchor_verifier = DSS.new(pub_key, 'fips-186-3', 'der')
        logging.info(f'Trust anchor loaded: {enc.Name.to_str(ta_name)}')

    def verify(self, sig_ptrs: enc.SignaturePtrs) -> bool:
        if (sig_ptrs.signature_info is None
                or sig_ptrs.signature_info.key_locator is None
                or sig_ptrs.signature_info.key_locator.name is None):
            logging.info(f'No signature')
            return False
        user_name = bytes(enc.Component.get_value(sig_ptrs.signature_info.key_locator.name[-3])).decode()
        key_name = bytes(enc.Component.get_value(sig_ptrs.signature_info.key_locator.name[-1])).hex()

        if (user_name, key_name) == self.trust_anchor_name:
            verifier = self.trust_anchor_verifier
        else:
            try:
                cert = self.repo.read_file(f'refs/users/{user_name[:2]}/{user_name}', f'KEY/{key_name}.cert')
            except KeyError as e:
                if e.args[0] == 0:
                    logging.warning(f'Repo {e.args[1]} does not exist')
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
