# -*- coding: utf-8 -*-
"""Offline accident judgment analysis: Excel in, Word report out."""

__all__ = ["JudgmentAnalysisDialog"]


def __getattr__(name):
    if name == "JudgmentAnalysisDialog":
        from judgment_analysis.dialog import JudgmentAnalysisDialog

        return JudgmentAnalysisDialog
    raise AttributeError("module %r has no attribute %r" % (__name__, name))
