"""Fake OpenAI-style clients for model calls in tests."""

import json
from types import SimpleNamespace


def reply(content="", tool_calls=()):
    """One chat completion. tool_calls: (name, arguments) pairs."""
    calls = [
        SimpleNamespace(id=f"call-{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
        for i, (name, args) in enumerate(tool_calls)
    ]
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=calls or None))])


class ScriptedChat:
    """Answers chat.completions.create with the scripted replies in order; repeats the last one."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
