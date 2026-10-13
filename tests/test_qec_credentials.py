"""QEC credentials must not replace the Diagnosis Viewer service entry."""

from ntf_insight.acquisition import credentials


def test_qec_ssso_passwords_are_separate_from_diagnosis_viewer(monkeypatch):
    class FakeRing:
        values = {}

        def get_password(self, service, name):
            return self.values.get((service, name))

        def set_password(self, service, name, value):
            self.values[(service, name)] = value

        def delete_password(self, service, name):
            self.values.pop((service, name), None)

    ring = FakeRing()
    monkeypatch.setattr(credentials, "_keyring", lambda: ring)
    credentials.save_credentials("quick-user", "quick-secret")
    credentials.save_credentials(
        "qec-user", "qec-secret", service_name=credentials.QEC_SERVICE_NAME
    )
    assert credentials.load_saved_credentials().user_id == "quick-user"
    assert credentials.load_saved_credentials(
        service_name=credentials.QEC_SERVICE_NAME
    ).user_id == "qec-user"
    credentials.clear_saved_credentials(service_name=credentials.QEC_SERVICE_NAME)
    assert credentials.load_saved_credentials(service_name=credentials.QEC_SERVICE_NAME) is None
    assert credentials.load_saved_credentials().password == "quick-secret"
