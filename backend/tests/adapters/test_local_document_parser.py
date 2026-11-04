from app.adapters.factory import make_document_parser
from tests.contract.document_parser_contract import DocumentParserContract


class TestLocalDocumentParser(DocumentParserContract):
    def make_adapter(self):
        return make_document_parser()
