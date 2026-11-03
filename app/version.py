VERSION = '0.18.0'
# Material releases follow the upstream version series; fork updates use VERSION.
UPSTREAM_VERSION = '1.4.2'

def material_compatibility(value):
    return UPSTREAM_VERSION if value == VERSION else value
