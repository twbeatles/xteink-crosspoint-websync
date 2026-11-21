"""macOS 토스트 AppleScript 이스케이프 테스트."""

from websync.integrations.notifier import ToastNotifier


def test_macos_toast_escapes_backslash_and_quote(monkeypatch):
    """역슬래시·큰따옴표가 모두 이스케이프되어야 스크립트 문자열이 깨지지 않는다."""
    import websync.integrations.notifier as notifier_module

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv

        class Dummy:
            pass

        return Dummy()

    monkeypatch.setattr(notifier_module.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(notifier_module.sys, "platform", "darwin")
    ToastNotifier.show_toast('a\\b"c', 'x\\y"z')
    script = captured["argv"][captured["argv"].index("-e") + 1]
    assert "a\\\\b\\\"c" in script
    assert "x\\\\y\\\"z" in script
