"""Presets for the merged (flask + werkzeug + jinja) graph.

Traces are the same scenarios used in src/tests/test_traversal.py.
That file is not imported here — it executes on import and is for
CLI testing only. This file is the web-app-safe equivalent.
"""

MERGED_PRESETS = {
    "tc1": {
        "label": "TC1 — NotFound: 404 (flask → werkzeug)",
        "trace": """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1596, in wsgi_app
    response = self.full_dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 982, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File "/output/clones/flask/src/flask/app.py", line 881, in handle_user_exception
    reraise(exc_type, exc_value, tb)
  File "/output/clones/werkzeug/src/werkzeug/routing/map.py", line 691, in match
    raise NotFound() from None
werkzeug.exceptions.NotFound: 404 Not Found: The requested URL was not found on the server.
""",
    },

    "tc2": {
        "label": "TC2 — MethodNotAllowed: 405 (flask → werkzeug)",
        "trace": """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1596, in wsgi_app
    response = self.full_dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 846, in handle_http_exception
    return handler(exc)
  File "/output/clones/werkzeug/src/werkzeug/routing/map.py", line 686, in match
    raise MethodNotAllowed(valid_methods=list(e.have_match_for)) from None
werkzeug.exceptions.MethodNotAllowed: 405 Method Not Allowed: The method is not allowed for the requested URL.
""",
    },

    "tc3": {
        "label": "TC3 — TemplateNotFound (flask → jinja → loaders, 3 hops)",
        "trace": """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 982, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File "/output/clones/flask/src/flask/templating.py", line 148, in render_template
    return _render(ctx, t, ctx_dict)
  File "/output/clones/flask/src/flask/templating.py", line 135, in _render
    rv = template.render(context)
  File "/output/clones/jinja/src/jinja2/environment.py", line 999, in get_template
    return self._load_template(name, globals)
  File "/output/clones/jinja/src/jinja2/environment.py", line 974, in _load_template
    template = self.loader.load(self, name, self.make_globals(globals))
  File "/output/clones/jinja/src/jinja2/loaders.py", line 215, in get_source
    raise TemplateNotFound(template)
jinja2.exceptions.TemplateNotFound: dashboard.html
""",
    },

    "tc4": {
        "label": "TC4 — UndefinedError: variable missing in template (flask → jinja → runtime)",
        "trace": """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1008, in full_dispatch_request
    rv = self.dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 982, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File "/output/clones/flask/src/flask/templating.py", line 148, in render_template
    return _render(ctx, t, ctx_dict)
  File "/output/clones/flask/src/flask/templating.py", line 135, in _render
    rv = template.render(context)
  File "/output/clones/jinja/src/jinja2/environment.py", line 1290, in render
    self.environment.handle_exception()
  File "/output/clones/jinja/src/jinja2/environment.py", line 953, in handle_exception
    raise rewrite_traceback_stack(source=source)
  File "/output/clones/jinja/src/jinja2/runtime.py", line 922, in _fail_with_undefined_error
    raise UndefinedError(hint)
jinja2.exceptions.UndefinedError: 'order' is undefined
""",
    },

    "tc5": {
        "label": "TC5 — RuntimeError: working outside application context (flask teardown)",
        "trace": """
Traceback (most recent call last):
  File "/output/clones/flask/src/flask/app.py", line 1596, in wsgi_app
    response = self.full_dispatch_request(ctx)
  File "/output/clones/flask/src/flask/app.py", line 1037, in finalize_request
    response = self.process_response(ctx, response)
  File "/output/clones/flask/src/flask/app.py", line 1410, in process_response
    self.do_teardown_request(ctx, exc)
  File "/output/clones/flask/src/flask/app.py", line 1436, in do_teardown_request
    func(exc)
  File "/output/clones/flask/src/flask/ctx.py", line 464, in pop
    self.app.do_teardown_appcontext(exc)
  File "/output/clones/flask/src/flask/app.py", line 1469, in do_teardown_appcontext
    func(exc)
RuntimeError: Working outside of application context.
""",
    },

    "tc6": {
        "label": "TC6 — Natural language: Jinja2 template loader broken (TF-IDF path)",
        "trace": """
Template rendering is broken. When users request pages that require Jinja2 templates,
the template loader cannot find the template file and raises a TemplateNotFound error.
The issue seems to be in how the Jinja2 environment loads templates from the file system.
""",
    },
}
