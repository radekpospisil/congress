# Copyright (c) 2014 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

from oslo.config import cfg
from oslo.db import exception as db_exc
from oslo.utils import importutils

from congress.datasources import constants
from congress.db import api as db
from congress.db import datasources as datasources_db
from congress.dse import d6cage
from congress import exception
from congress.openstack.common import log as logging
from congress.openstack.common import uuidutils

LOG = logging.getLogger(__name__)


class DataSourceManager(object):

    loaded_drivers = {}

    @classmethod
    def add_datasource(cls, item, deleted=False, update_db=True):
        req = cls.make_datasource_dict(item)
        # If update_db is True, new_id will get a new value from the db.
        new_id = req['id']
        driver_info = cls.get_driver_info(item['driver'])
        session = db.get_session()
        try:
            with session.begin(subtransactions=True):
                LOG.debug("adding datasource %s", req['name'])
                if update_db:
                    LOG.debug("updating db")
                    datasource = datasources_db.add_datasource(
                        id_=req['id'],
                        name=req['name'],
                        driver=req['driver'],
                        config=req['config'],
                        description=req['description'],
                        enabled=req['enabled'],
                        session=session)
                    new_id = datasource['id']

                cage = d6cage.d6Cage()
                engine = cage.service_object('engine')
                try:
                    LOG.debug("creating policy %s", req['name'])
                    engine.create_policy(req['name'])
                except KeyError:
                    # FIXME(arosen): we need a better exception then
                    # key error being raised here
                    raise DatasourceNameInUse(name=req['name'])
                cage.createservice(name=req['name'],
                                   moduleName=driver_info['module'],
                                   args=item['config'],
                                   module_driver=True,
                                   type_='datasource_driver',
                                   id_=new_id)
                service = cage.service_object(req['name'])
                engine.set_schema(req['name'], service.get_schema())

        except db_exc.DBDuplicateEntry:
            raise DatasourceNameInUse(name=req['name'])
        new_item = dict(item)
        new_item['id'] = new_id
        return cls.make_datasource_dict(new_item)

    @classmethod
    def validate_configured_drivers(cls):
        result = {}
        for driver_path in cfg.CONF.drivers:
            obj = importutils.import_class(driver_path)
            driver = obj.get_datasource_info()
            if driver['id'] in result:
                raise BadConfig(_("There is a driver loaded already with the"
                                  "driver name of %s")
                                % driver['id'])
            driver['module'] = driver_path
            result[driver['id']] = driver
        cls.loaded_drivers = result

    @classmethod
    def make_datasource_dict(cls, req, fields=None):
        result = {'id': req.get('id') or uuidutils.generate_uuid(),
                  'name': req.get('name'),
                  'driver': req.get('driver'),
                  'description': req.get('description'),
                  'type': None,
                  'enabled': req.get('enabled', True)}
        # NOTE(arosen): we store the config as a string in the db so
        # here we serialize it back when returning it.
        if type(req.get('config')) in [str, unicode]:
            result['config'] = json.loads(req['config'])
        else:
            result['config'] = req.get('config')

        return cls._fields(result, fields)

    @classmethod
    def _fields(cls, resource, fields):
        if fields:
            return dict(((key, item) for key, item in resource.items()
                         if key in fields))
        return resource

    @classmethod
    def get_datasources(cls, filter_secret=False):
        """Return the created datasources.

        This returns what datasources the database contains, not the
        datasources that this server instance is running.
        """

        results = []
        for datasouce_driver in datasources_db.get_datasources():
            result = cls.make_datasource_dict(datasouce_driver)
            if filter_secret:
                hide_fields = cls.get_driver_info(result['driver'])['secret']
                for hide_field in hide_fields:
                    result['config'][hide_field] = "<hidden>"
            results.append(result)
        return results

    @classmethod
    def get_datasource(cls, id_):
        """Return the created datasource."""
        result = datasources_db.get_datasource(id_)
        if not result:
            raise DatasourceNotFound(id=id_)
        return cls.make_datasource_dict(result)

    @classmethod
    def get_driver_info(cls, driver):
        driver = cls.loaded_drivers.get(driver)
        if not driver:
            raise DriverNotFound(id=driver)
        return driver

    @classmethod
    def get_driver_schema(cls, datasource_id):
        driver = cls.get_driver_info(datasource_id)
        obj = importutils.import_class(driver['module'])
        return obj.get_schema()

    @classmethod
    def get_datasource_schema(cls, datasource_id):
        datasource = datasources_db.get_datasource(datasource_id)
        if not datasource:
            raise DatasourceNotFound(id=datasource_id)
        driver = cls.get_driver_info(datasource.driver)
        if driver:
            # NOTE(arosen): raises if not found
            driver = cls.get_driver_info(
                driver['id'])
            obj = importutils.import_class(driver['module'])
            return obj.get_schema()

    @classmethod
    def delete_datasource(cls, datasource_id, update_db=True):
        datasource = cls.get_datasource(datasource_id)
        session = db.get_session()
        with session.begin(subtransactions=True):
            cage = d6cage.d6Cage()
            engine = cage.service_object('engine')
            try:
                engine.delete_policy(datasource['name'],
                                     disallow_dangling_refs=True)
            except exception.DanglingReference as e:
                raise e
            except KeyError:
                raise DatasourceNotFound(id=datasource_id)
            if update_db:
                result = datasources_db.delete_datasource(
                    datasource_id, session)
                if not result:
                    raise DatasourceNotFound(id=datasource_id)
            cage.deleteservice(datasource['name'])

    @classmethod
    def get_drivers_info(cls):
        return [driver for driver in cls.loaded_drivers.values()]

    @classmethod
    def validate_create_datasource(cls, req):
        driver = req['driver']
        config = req['config']
        for loaded_driver in cls.loaded_drivers.values():
            if loaded_driver['id'] == driver:
                specified_options = set(config.keys())
                valid_options = set(loaded_driver['config'].keys())
                # Check that all the specified options passed in are
                # valid configuration options that the driver exposes.
                invalid_options = specified_options - valid_options
                if invalid_options:
                    raise InvalidDriverOption(invalid_options=invalid_options)

                # check that all the required options are passed in
                required_options = set(
                    [k for k, v in loaded_driver['config'].iteritems()
                     if v == constants.REQUIRED])
                missing_options = required_options - specified_options
                if missing_options:
                    missing_options = ', '.join(missing_options)
                    raise MissingRequiredConfigOptions(
                        missing_options=missing_options)
                return loaded_driver

        # If we get here no datasource driver match was found.
        raise InvalidDriver(driver=req)

    @classmethod
    def create_table_dict(cls, tablename, schema):
        # FIXME(arosen): Should not be returning None
        # here for description.
        cols = [{'name': x, 'description': 'None'}
                for x in schema[tablename]]
        return {'table_id': tablename,
                'columns': cols}


class BadConfig(exception.BadRequest):
    pass


class DatasourceDriverException(exception.CongressException):
    pass


class MissingRequiredConfigOptions(BadConfig):
    msg_fmt = _("Missing required config options: %(missing_options)s")


class InvalidDriver(BadConfig):
    msg_fmt = _("Invalid driver: %(driver)s")


class InvalidDriverOption(BadConfig):
    msg_fmt = _("Invalid driver options: %(invalid_options)s")


class DatasourceNameInUse(exception.Conflict):
    msg_fmt = _("Datasource already in use with name %(name)s")


class DatasourceNotFound(exception.NotFound):
    msg_fmt = _("Datasource not found %(id)s")


class DriverNotFound(exception.NotFound):
    msg_fmt = _("Driver not found %(id)s")
