from app.modules.rag.query.answering.pageindex_agent.citations.verifier import verify_citations


class CitationStreamFormatter:
    def __init__(self, sources_data: list[dict]):
        self.sources_data = sources_data
        self.buffer = ""

    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk

        last_paren = self.buffer.rfind("(")
        if last_paren != -1:
            after_paren = self.buffer[last_paren:]
            if ")" not in after_paren:
                if after_paren.startswith("(^") or "(^".startswith(after_paren):
                    ready_part = self.buffer[:last_paren]
                    pending_part = self.buffer[last_paren:]

                    processed = verify_citations(
                        ready_part,
                        self.sources_data,
                    )
                    self.buffer = pending_part
                    return processed

        processed = verify_citations(
            self.buffer,
            self.sources_data,
        )
        self.buffer = ""
        return processed

    def flush(self) -> str:
        processed = verify_citations(
            self.buffer,
            self.sources_data,
        )
        self.buffer = ""
        return processed
