import unittest

from features.role_audit_reason import RoleAuditReason, encode_role_audit_reason, parse_role_audit_reason


class RoleAuditReasonTests(unittest.TestCase):
    def test_wire_format_and_maximum_discord_id(self):
        actor_id = (1 << 64) - 1
        encoded = encode_role_audit_reason(actor_id, 'helper', 'role_grant')
        self.assertEqual(encoded, 'con9sole:member-role:v1 18446744073709551615 helper role_grant')
        self.assertEqual(parse_role_audit_reason(encoded), RoleAuditReason(actor_id, 'helper', 'role_grant'))

    def test_reject_legacy_malformed_or_unknown_reasons(self):
        for reason in (None, '/role_grant by someone', 'Member wording preference',
                       'con9sole:member-role:v2 7 admin role_grant', 'x' * 512):
            self.assertIsNone(parse_role_audit_reason(reason))
        for fields in ('01 admin role_grant', '0 admin role_grant', '１２ admin role_grant',
                       '18446744073709551616 admin role_grant', '+1 admin role_grant',
                       '7 self role_grant', '7 helper bulk_role_revoke', '7 bot role_grant',
                       '7 admin unknown', '7 helper role_grant extra', '7 self news_grant\n'):
            with self.subTest(fields=fields):
                self.assertIsNone(parse_role_audit_reason(f'con9sole:member-role:v1 {fields}'))

    def test_encoder_refuses_invalid_metadata(self):
        for actor in (0, -1, 1 << 64, True, '7'):
            with self.assertRaises(ValueError):
                encode_role_audit_reason(actor, 'self', 'news_grant')
        for kind, operation in (('unknown', 'role_grant'), ('self', 'arbitrary'),
                                ('helper', 'bulk_role_grant'), ('admin', 'language_revoke')):
            with self.assertRaises(ValueError):
                encode_role_audit_reason(7, kind, operation)
