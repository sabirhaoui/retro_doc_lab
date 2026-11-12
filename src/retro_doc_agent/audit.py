"""Architecture and static-control audit stage."""


def run(static_audit, output, meta, excluded, unread):
    if static_audit is None:
        raise ValueError('Static audit requires an inspected local source tree')
    static_audit.write(output, meta, excluded, unread)
