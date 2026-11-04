import unittest, app

class T(unittest.TestCase):
    def test_templates_pass_sandbox(self):
        for k, code in app.SCRIPT_TEMPLATES.items():
            ok, err = app.validate_python_script(code)[:2] if isinstance(app.validate_python_script(code), tuple) else (app.validate_python_script(code), None)
            self.assertTrue(ok, f"{k}: {err}")
    def test_no_false_import_claim(self):
        self.assertNotIn("Python imports in the editor!", app.KNOWLEDGE_BASE["import"])
        self.assertNotIn("Import support", app.IOT_SIMULATOR_SYSTEM_PROMPT)
    def test_new_openai_client(self):
        import inspect
        self.assertNotIn("ChatCompletion", inspect.getsource(app.call_openai_api))
if __name__ == "__main__": unittest.main()

class P(unittest.TestCase):
    def test_battery_presets_usable_in_script(self):
        code = 'g = Gateway("gw")\ns = Sensor("s", battery_mah=CR2032)\ns.connect(g, distance_m=5)\n'
        r = app.validate_python_script(code)
        ok = r[0] if isinstance(r, tuple) else r
        self.assertTrue(ok, r)
