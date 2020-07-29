import logging
import html

from pyhocon import ConfigTree, ConfigFactory  # noqa: F401
from typing import Any  # noqa: F401

from databuilder import Scoped

from databuilder.extractor.base_extractor import Extractor
from databuilder.extractor.restapi.rest_api_extractor import STATIC_RECORD_DICT
from databuilder.extractor.dashboard.tableau.tableau_dashboard_constants import EXCLUDED_PROJECTS,\
    EXTERNAL_CLUSTER_NAME
from databuilder.extractor.dashboard.tableau.tableau_dashboard_utils import TableauDashboardAuth,\
    TableauGraphQLApiExtractor, TableauDashboardUtils

from databuilder.rest_api.rest_api_query import RestApiQuery  # noqa: F401
from databuilder.rest_api.base_rest_api_query import BaseRestApiQuery  # noqa: F401

from databuilder.transformer.base_transformer import ChainedTransformer
from databuilder.transformer.dict_to_model import DictToModel, MODEL_CLASS

LOGGER = logging.getLogger(__name__)


class TableauDashboardTableExtractor(Extractor):
    """
    """

    def init(self, conf):
        # type: (ConfigTree) -> None

        self._conf = conf
        self._auth = TableauDashboardAuth(self._conf)
        self.query = """query {
          workbooks {
            name
            projectName
            upstreamTables {
              name
              schema
              database {
                name
                connectionType
              }
            }
          }
        }"""
        self._extractor = self._build_extractor()

        transformers = []
        dict_to_model_transformer = DictToModel()
        dict_to_model_transformer.init(
            conf=Scoped.get_scoped_conf(self._conf, dict_to_model_transformer.get_scope()).with_fallback(
                ConfigFactory.from_dict(
                    {MODEL_CLASS: 'databuilder.models.dashboard.dashboard_table.DashboardTable'})))
        transformers.append(dict_to_model_transformer)
        self._transformer = ChainedTransformer(transformers=transformers)

    def extract(self):
        # type: () -> Any

        record = self._extractor.extract()
        if not record:
            return None

        return self._transformer.transform(record=record)

    def get_scope(self):
        # type: () -> str

        return 'extractor.tableau_dashboard_table'

    def _build_extractor(self):
        """
        """
        extractor = TableauGraphQLDashboardTableExtractor()
        tableau_extractor_conf = \
            Scoped.get_scoped_conf(self._conf, extractor.get_scope())\
                  .with_fallback(self._conf)\
                  .with_fallback(ConfigFactory.from_dict({STATIC_RECORD_DICT: {'product': 'tableau'}
                                                          }
                                                         )
                                 )
        extractor.init(conf=tableau_extractor_conf, auth_token=self._auth.token, query=self.query)
        return extractor


class TableauGraphQLDashboardTableExtractor(TableauGraphQLApiExtractor):
    """docstring for TableauDashboardMetadataExtractor"""
    def execute(self):
        response = self.execute_query()

        workbooks_data = [workbook for workbook in response['workbooks']
                          if workbook['projectName'] not in self._conf.get_list(EXCLUDED_PROJECTS)]

        for workbook in workbooks_data:
            data = {}
            data['dashboard_group_id'] = workbook['projectName']
            data['dashboard_id'] = html.escape(workbook['name'])
            data['cluster'] = self._conf.get_string("cluster")
            data['table_ids'] = []

            for table in workbook['upstreamTables']:
                table_id_format = "{database}://{cluster}.{schema}/{table}"
                if table['schema'] != "":
                    cluster, database = self._conf.get_string("cluster"), self._conf.get_string("database")
                    if "." in table['name']:
                        schema, name = table['name'].split(".")
                    else:
                        schema, name = table['schema'], table['name']
                    schema, name = html.escape(schema), html.escape(name)
                else:
                    cluster = self._conf.get_string(EXTERNAL_CLUSTER_NAME)
                    database = TableauDashboardUtils.sanitize_database_name(
                        html.escape(table['database']['connectionType'])
                    )
                    schema = TableauDashboardUtils.sanitize_schema_name(html.escape(table['database']['name']))
                    name = TableauDashboardUtils.sanitize_table_name(html.escape(table['name']))

                table_id = table_id_format.format(
                    database=database,
                    cluster=cluster,
                    schema=schema,
                    table=name,
                )
                data['table_ids'].append(table_id)

            yield data
