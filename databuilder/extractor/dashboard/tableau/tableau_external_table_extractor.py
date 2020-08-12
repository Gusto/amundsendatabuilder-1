import logging

from pyhocon import ConfigFactory  # noqa: F401

from databuilder import Scoped

from databuilder.extractor.base_extractor import Extractor

import databuilder.extractor.dashboard.tableau.tableau_dashboard_constants as const
from databuilder.extractor.dashboard.tableau.tableau_dashboard_utils import TableauDashboardAuth,\
    TableauGraphQLApiExtractor, TableauDashboardUtils

from databuilder.transformer.base_transformer import ChainedTransformer
from databuilder.transformer.dict_to_model import DictToModel, MODEL_CLASS

LOGGER = logging.getLogger(__name__)


class TableauDashboardExternalTableExtractor(Extractor):
    """
    Creates the "external" Tableau tables.
    In this context, "external" tables are "tables" that are not from a typical database, and are loaded
    using some other data format, like CSV files.
    This extractor has been tested with the following types of external tables:
        Excel spreadsheets
        Text files (including CSV files)
        Salesforce connections
        Google Sheets connections

    Excel spreadsheets, Salesforce connections, and Google Sheets connections are all classified as
    "databases" in terms of Tableau's Metadata API, with their "subsheets" forming their "tables" when
    present. However, these tables are not assigned a schema, this extractor chooses to use the name
    parent sheet as the schema, and assign a new table to each subsheet. The connection type is
    always used as the database, and for text files, the schema is set using the EXTERNAL_SCHEMA_NAME
    config option. Since these external tables are usually named for human consumption only and often
    contain a wider range of characters, all inputs are transformed to remove any problematic
    occurences before they are inserted: see the sanitize methods TableauDashboardUtils for specifics.

    A more concrete example: if one had a Google Sheet titled "Growth by Region & County" with 2 subsheets called
    "FY19 Report" and "FY20 Report", two tables would be generated with the following keys:
    googlesheets://external.growth_by_region_county/FY_19_Report
    googlesheets://external.growth_by_region_county/FY_20_Report
    """

    API_VERSION = const.API_VERSION
    TABLEAU_HOST = const.TABLEAU_HOST
    SITE_NAME = const.SITE_NAME
    TABLEAU_ACCESS_TOKEN_NAME = const.TABLEAU_ACCESS_TOKEN_NAME
    TABLEAU_ACCESS_TOKEN_SECRET = const.TABLEAU_ACCESS_TOKEN_SECRET
    EXCLUDED_PROJECTS = const.EXCLUDED_PROJECTS
    EXTERNAL_CLUSTER_NAME = const.EXTERNAL_CLUSTER_NAME
    EXTERNAL_SCHEMA_NAME = const.EXTERNAL_SCHEMA_NAME
    EXTERNAL_TABLE_TYPES = const.EXTERNAL_TABLE_TYPES
    CLUSTER = const.CLUSTER
    DATABASE = const.DATABASE

    def init(self, conf):
        # type: (ConfigTree) -> None

        self._conf = conf
        self._auth = TableauDashboardAuth(self._conf)
        self.query = """query externalTables($externalTableTypes: [String]) {
          databases (filter: {connectionTypeWithin: $externalTableTypes}) {
            name
            connectionType
            description
            tables {
                name
            }
          }
        }"""
        self.query_variables = {'externalTableTypes': self._conf.get_list(const.EXTERNAL_TABLE_TYPES)}
        self._extractor = self._build_extractor()

        transformers = []
        dict_to_model_transformer = DictToModel()
        dict_to_model_transformer.init(
            conf=Scoped.get_scoped_conf(self._conf, dict_to_model_transformer.get_scope()).with_fallback(
                ConfigFactory.from_dict(
                    {MODEL_CLASS: 'databuilder.models.table_metadata.TableMetadata'})))
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

        return 'extractor.tableau_external_table'

    def _build_extractor(self):
        """
        """
        extractor = TableauGraphQLExternalTableExtractor()
        tableau_extractor_conf = \
            Scoped.get_scoped_conf(self._conf, extractor.get_scope())\
                  .with_fallback(self._conf)\
                  .with_fallback(ConfigFactory.from_dict({}))
        extractor.init(conf=tableau_extractor_conf,
                       auth_token=self._auth.token,
                       query=self.query,
                       query_variables=self.query_variables)
        return extractor


class TableauGraphQLExternalTableExtractor(TableauGraphQLApiExtractor):
    """
    Implements the extraction-time logic for parsing the GraphQL result and transforming into a dict
    that fills the TableMetadata model.
    """
    def execute(self):
        response = self.execute_query()

        for table in response['databases']:
            if table['connectionType'] in ['google-sheets', 'salesforce', 'excel-direct']:
                for downstreamTable in table['tables']:
                    data = {
                        'cluster': self._conf.get_string(TableauGraphQLApiExtractor.EXTERNAL_CLUSTER_NAME),
                        'database': TableauDashboardUtils.sanitize_database_name(
                            table['connectionType']
                        ),
                        'schema': TableauDashboardUtils.sanitize_schema_name(table['name']),
                        'name': TableauDashboardUtils.sanitize_table_name(downstreamTable['name']),
                        'description': table['description']
                    }
                    yield data
            else:
                data = {
                    'cluster': self._conf.get_string(TableauGraphQLApiExtractor.EXTERNAL_CLUSTER_NAME),
                    'database': TableauDashboardUtils.sanitize_database_name(table['connectionType']),
                    'schema': self._conf.get_string(TableauGraphQLApiExtractor.EXTERNAL_SCHEMA_NAME),
                    'name': TableauDashboardUtils.sanitize_table_name(table['name']),
                    'description': table['description']
                }
                yield data
