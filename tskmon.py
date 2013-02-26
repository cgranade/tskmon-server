#!/usr/bin/python
# -*- coding: utf-8 -*-
##
# tskmon.py: Main file for the tskmon task monitoring server.
##
# © 2013 Christopher E. Granade (cgranade@gmail.com)
#
# This file is a part of the tskmon project.
# Licensed under the AGPL version 3.
##
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
##

## IMPORTS #####################################################################

import datetime
import json

import cherrypy

from google.appengine.ext import db
from google.appengine.ext.webapp.util import run_wsgi_app
from google.appengine.api import users, oauth

from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('_templates'))

## CONSTANTS ###################################################################

DEBUG = True

## FUNCTIONS ###################################################################

## User Management Functions ##

def oauth_or_session():
    try:
        user = oauth.get_current_user()
        if user is None:
            return users.get_current_user()
        else:
            return user
    except oauth.OAuthRequestError:
        return users.get_current_user()

## DB MODELS ###################################################################

class Task(db.Model):
    title = db.StringProperty()
    status = db.StringProperty()
    max_progress = db.IntegerProperty()
    progress = db.IntegerProperty()
    date_started = db.DateTimeProperty(auto_now_add=True)
    owner = db.UserProperty()
    
    @staticmethod
    def from_json(obj):
        task = Task()
        task.title = obj['title']
        task.status = obj['status']
        task.max_progress = obj['max']
        task.progress = obj['progress']
        # TODO: assign owner!
        return task
        
    def to_json(self):
        return {
            'title': self.title,
            'status': self.status,
            'max': self.max_progress,
            'progress': self.progress,
            'date_started': self.date_started,
            # TODO: fix this with an actual URI!
            'uri': '/api/task/{}'.format(self.key().id())
        }

## SERIALIZATION ###############################################################

## JSON Handling ##

class CustomJSONEncoder(json.JSONEncoder):
    """
    Adds support to `~json.JSONEncoder` for serializing objects specific to the
    tskmon API.
    """
    
    def default(self, obj):
        if hasattr(obj, "to_json"):
            return obj.to_json()
        elif isinstance(obj, Exception):
            return error_to_json(obj)
        elif isinstance(obj, datetime.datetime):
            return obj.isoformat()
        else:
            return super(CustomJSONEncoder, self).default(obj)
    
json_encoder = CustomJSONEncoder()
    
def json_handler(*args, **kwargs):
    """
    Implements a JSON handler for CherryPy using the `CustomJSONEncoder`
    class defined above.
    """
    # Adapted from cherrypy/lib/jsontools.py
    value = cherrypy.serving.request._json_inner_handler(*args, **kwargs)
    return json_encoder.iterencode(value)

def error_to_json(obj):
    """
    Given an exception object, formats it as a dictonary for processing by
    the `json` module.
    """
    return {
        "result": "error",
        "error": {
            'type': type(obj).__name__,
            "msg": str(obj)
        }
    }

## EXCEPTIONS ##################################################################

class AuthenticationError(RuntimeError):
    def to_json(self):
        d = error_to_json(self)
        return d

## PAGES #######################################################################

class TaskApi(object):
    @cherrypy.expose
    @cherrypy.tools.json_out()
    def index(self, **args):
        user = oauth_or_session()
        if user is None:
            return AuthenticationError()
            
        # FIXME: won't work well with lots of tasks, so we need to implement
        #        limits here.
        return list(
            Task.all().filter('owner =', user) 
        )
        
    # TODO: make this more RESTful.
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def new(self, title=None, status=None, max=100, progress=0, **args):
        user = oauth_or_session()
        if not user:
            # TODO: integrate API errors with CherryPy status handling.
            return AuthenticationError()
            
        progress = int(progress)
        max = int(max)
        if progress > max or progress < 0:
            return ValueError("Progress must be between 0 and max.")
            
        task = Task()
        task.owner = user
        task.max_progress = max
        task.progress = progress
        task.title = title
        task.status = status
        
        try:
            task.put()
            return {
                'result': 'success',
                'new_task': task
            }
        except Exception as ex:
            # FIXME: this could expose sensitive info, but is
            #        done for debugging.
            return ex
            

class ApiRoot(object):
    tasks = TaskApi()
    
    @cherrypy.expose
    @cherrypy.tools.json_in()
    @cherrypy.tools.json_out()
    def task(self, id, **args):
        task = Task.get_by_id(int(id))
        
        if task is None:
            raise cherrypy._cperror.HTTPError(404)
            
        if task.owner != oauth_or_session():
            return AuthenticationError()
        else:
            # Do something based on the method.
            meth = cherrypy.request.method.upper()
            if meth == "GET":
                return task
            elif meth == "POST":
                # TODO: read query parameters, too.
                req_body = cherrypy.request.json
                if 'title' in req_body.keys():
                    task.title = req_body['title']
                if 'status' in req_body.keys():
                    task.status = req_body['status']
                if 'progress' in req_body.keys():
                    task.progress = req_body['progress']
                if 'max' in req_body.keys():
                    task.max_progress = req_body['max']
                task.put()
                return {
                    "result": "success",
                    "updated_task": task
                }
            elif meth == "DELETE":
                task.delete()
                return {
                    "result": "success",
                    "deleted_task": task
                }
            else:
                # TODO: raise an HTTP error here.
                return
        
class Root(object):
    api = ApiRoot()
    
    @cherrypy.expose
    def index(self):
        tmpl = env.get_template('index.html')
        return tmpl.render(users=users)

## APPLICATION CONFIG ##########################################################

app = cherrypy.tree.mount(Root(), '/', config={
    '/': {
        'tools.json_out.handler': json_handler
    }
})
run_wsgi_app(app)

