package com.coremasterkb.serving.mapper.result;

/** Aggregated count of segments sharing a section_path, for a given entity set. */
public class SectionPathCountRow {
    private String sectionPath;
    private int cnt;

    public String getSectionPath() { return sectionPath; }
    public void setSectionPath(String sectionPath) { this.sectionPath = sectionPath; }

    public int getCnt() { return cnt; }
    public void setCnt(int cnt) { this.cnt = cnt; }
}
