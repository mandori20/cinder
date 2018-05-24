# Copyright 2018 Nexenta Systems, Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
"""
Unit tests for NexentaStor 5 REST API helper
"""

import mock
import requests
import uuid

from cinder import exception
from cinder import test
from cinder.volume.drivers.nexenta.ns5 import jsonrpc
from mock import patch
from oslo_serialization import jsonutils
from requests import adapters

HOST = '1.1.1.1'
USERNAME = 'user'
PASSWORD = 'pass'


def gen_response(code=200, json=None):
    r = requests.Response()
    r.headers['Content-Type'] = 'application/json'
    r.encoding = 'utf8'
    r.status_code = code
    r.reason = 'FAKE REASON'
    r.raw = mock.Mock()
    r._content = ''
    if json:
        r._content = jsonutils.dumps(json)
    return r


class TestNexentaJSONProxyAuth(test.TestCase):

    @patch('cinder.volume.drivers.nexenta.ns5.jsonrpc.requests.post')
    def test_https_auth(self, post):
        use_https = True
        port = 8443
        auth_uri = 'auth/login'
        rnd_url = 'some/random/url'
        ssl = False

        class PostSideEffect(object):
            def __call__(self, *args, **kwargs):
                r = gen_response()
                if args[0] == '{}://{}:{}/{}'.format(
                        'https', HOST, port, auth_uri):
                    token = uuid.uuid4().hex
                    content = {'token': token}
                    r._content = jsonutils.dumps(content)
                return r
        post_side_effect = PostSideEffect()
        post.side_effect = post_side_effect

        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()
                self.counter = 0

            def send(self, request, *args, **kwargs):
                # an url is being requested for the second time
                if self.counter == 1:
                    # make the fake backend respond 401
                    r = gen_response(401)
                    r._content = ''
                    r.connection = mock.Mock()
                    r_ = gen_response(json={'data': []})
                    r.connection.send = lambda prep, **kwargs_: r_
                else:
                    r = gen_response(json={'data': []})
                r.request = request
                self.counter += 1
                return r

        nef = jsonrpc.NexentaJSONProxy(HOST, port, USERNAME, PASSWORD,
                                       use_https, 'pool', ssl)
        adapter = TestAdapter()
        nef.session.mount('{}://{}:{}/{}'.format('https', HOST, port, rnd_url),
                          adapter)

        # successful authorization
        self.assertEqual(nef.get(rnd_url), {'data': []})

        # session timeout simulation. Client must authenticate newly
        self.assertEqual(nef.get(rnd_url), {'data': []})
        # auth URL mast be requested two times at this moment
        self.assertEqual(2, post.call_count)

        # continue with the last (second) token
        self.assertEqual(nef.get(rnd_url), {'data': []})
        # auth URL must be requested two times
        self.assertEqual(2, post.call_count)


class TestNexentaJSONProxy(test.TestCase):

    def setUp(self):
        super(TestNexentaJSONProxy, self).setUp()
        self.nef = jsonrpc.NexentaJSONProxy(
            HOST, 0, USERNAME, PASSWORD, False, 'pool', False)

    def gen_adapter(self, code, json=None):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                r = gen_response(code, json)
                r.request = request
                return r

        return TestAdapter()

    def test_post(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), self.gen_adapter(201, random_dict))
        self.assertEqual(self.nef.post(rnd_url), random_dict)

    def test_delete(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), self.gen_adapter(201, random_dict))
        self.assertEqual(self.nef.delete(rnd_url), random_dict)

    def test_put(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), self.gen_adapter(201, random_dict))
        self.assertEqual(self.nef.put(rnd_url), random_dict)

    def test_get_200(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), self.gen_adapter(200, random_dict))
        self.assertEqual(self.nef.get(rnd_url), random_dict)

    def test_get_201(self):
        random_dict = {'data': uuid.uuid4().hex}
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), self.gen_adapter(201, random_dict))
        self.assertEqual(self.nef.get(rnd_url), random_dict)

    def test_get_500(self):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                json = {
                    'code': 'NEF_ERROR',
                    'message': 'Some error'
                }
                r = gen_response(500, json)
                r.request = request
                return r

        adapter = TestAdapter()
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), adapter)
        self.assertRaises(exception.NexentaException, self.nef.get, rnd_url)

    def test_get__not_nef_error(self):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                r = gen_response(404)
                r._content = 'Page Not Found'
                r.request = request
                return r

        adapter = TestAdapter()
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), adapter)
        self.assertRaises(exception.VolumeBackendAPIException, self.nef.get,
                          rnd_url)

    def test_get__not_nef_error_empty_body(self):
        class TestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(TestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                r = gen_response(404)
                r.request = request
                return r

        adapter = TestAdapter()
        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), adapter)
        self.assertRaises(exception.VolumeBackendAPIException, self.nef.get,
                          rnd_url)

    def test_202(self):
        redirect_url = 'redirect/url'

        class RedirectTestAdapter(adapters.HTTPAdapter):

            def __init__(self):
                super(RedirectTestAdapter, self).__init__()

            def send(self, request, *args, **kwargs):
                json = {
                    'links': [{'href': redirect_url}]
                }
                r = gen_response(202, json)
                r.request = request
                return r

        rnd_url = 'some/random/url'
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, rnd_url), RedirectTestAdapter())
        self.nef.session.mount('{}://{}:{}/{}'.format(
            'http', HOST, 8080, redirect_url), self.gen_adapter(201))
        self.assertIsNone(self.nef.get(rnd_url))
