"""ML package.

Import the entry points from their modules: ``from src.ml.predict import predict``,
``from src.ml.explain import explain`` and ``from src.ml.features import build``. The
package does not re-export them, because a function with the name of its module would
hide the module (``src.ml.predict`` would be the function).
"""
