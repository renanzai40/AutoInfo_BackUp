---
title: Modeling Device Capabilities for Analytics
domain: online-video
tier: 01-Raw
entry_id: online-video-general-modeling-device-capabilities-for-analytics
source_url: https://netflixtechblog.com/modeling-device-capabilities-for-analytics-e7607acebde8?source=rss----2615bd06b42e---4
source_type: rss
source_platform: rss
collected_at: '2026-07-31T16:01:02+00:00'
summary: Netflix built a comprehensive device capability data model to track hardware limitations across its diverse ecosystem
  of streaming devices. By using cumulative tables and histogram analytics, they can make data-driven decisions about which
  features to enable on specific devices, optimizing user experience and accelerating innovation.
tags: []
quality_tier: 2
relevance_score: 0.0
dedup_status: duplicate
source_score: 70.0
language: en
user_id: ''
version: 1
previous_version: 0
supersedes: ''
trace_id: a98f6f76-2843-4be5-a1df-6f6563111754
quality_flags:
  G0-SchemaIntegrity: false
  G1-SourceAuthority: false
  G1-TosCompliance: false
  G2-Dedup: true
  G3-RelevanceScoring: true
  G4-SummaryFactual: false
tos_compliant: true
tos_classification: open
---

## Original Content
<p>by <a href="https://www.linkedin.com/in/aarti-laddha-70666557/">Aarti Laddha</a>, <a href="https://www.linkedin.com/in/richardjcool/">Richard Diaz-Cool</a>, <a href="https://www.linkedin.com/in/rishikaidnani/">Rishika Idnani</a>, <a href="https://www.linkedin.com/in/venkatesh-selvaraj-88824137/">Venkatesh Selveraj</a></p><p>Netflix supports a vast and evolving set of features and content types, ranging from 4K streaming and immersive audio to live streaming and cloud gaming, across a diverse ecosystem of devices. However, not all devices are created equal. Hardware limitations such as available RAM, CPU cores, display capabilities, or platform support mean that some features cannot be supported on certain device models. To ensure the best possible user experience, we rely on a deep understanding of device capabilities. We have invested in building a comprehensive device capability data model and integrating feature flags from internal systems, paving the way for smarter, more granular feature management across our global device landscape. This approach helps us identify bottlenecks in feature penetration and accelerates the pace of innovation.</p><p>We have designed our data storage and modeling strategies to efficiently support analytics at scale. We use a cumulative table to process information about the device’s capabilities. This table is structured to efficiently capture the latest state of each device and its associated capabilities (like Screen resolutions, Video Profiles Supported, Surround Sound, RAM size etc) making it ideal for analytics and reporting use cases.</p><pre>{<br />&quot;Screen Height&quot;: [&quot;720&quot;],<br />&quot;Screen Width&quot;: [&quot;1280&quot;],<br />&quot;Video Profiles&quot;: <br />[<br />&quot;playready&quot;,<br />&quot;hevc&quot;,<br />],<br />}</pre><p>For aggregate analytics, we leverage a histogram table that captures active device counts over the past 28 days, broken down by device model and software version. This table also records the number of devices supporting specific capabilities, enabling detailed distribution analysis. One use case for this histogram data is to analyze the distribution of external display capabilities attached to streaming sticks. For example, the histogram below shows that out of total X number of devices, all supported the HD profile (playready), while only 20% devices supported the UHD profile (hevc).</p><pre>{<br />&quot;Video Profiles&quot;: {<br />      &quot;playready&quot;: 100%, # HD profile<br />      &quot;hevc&quot;: 20% # UHD profile<br />}<br />}</pre><p>We have built analytical products that leverage these datasets to provide a comprehensive view of feature reach such as 4K Ultra HD, Netflix Spatial Audio, Cloud Gaming and the latest UI. By relying on data-driven insights, we can make informed decisions about which features to enable on specific devices, ensuring both performance and reliability.</p><img alt="" height="1" src="https://medium.com/_/stat?event=post.clientViewed&amp;referrerSource=full_rss&amp;postId=e7607acebde8" width="1" /><hr /><p><a href="https://netflixtechblog.com/modeling-device-capabilities-for-analytics-e7607acebde8">Modeling Device Capabilities for Analytics</a> was originally published in <a href="https://netflixtechblog.com">Netflix TechBlog</a> on Medium, where people are continuing the conversation by highlighting and responding to this story.</p>

## Summary
Netflix built a comprehensive device capability data model to track hardware limitations across its diverse ecosystem of streaming devices. By using cumulative tables and histogram analytics, they can make data-driven decisions about which features to enable on specific devices, optimizing user experience and accelerating innovation.

## Key Points
- Netflix created a device capability data model integrating feature flags from internal systems to manage features across a diverse global device landscape.
- A cumulative table captures the latest state of each device's capabilities including screen resolution, video profiles, surround sound support, and RAM size.
- A histogram table tracks active device counts over 28 days broken down by device model and software version, enabling distribution analysis.
- Analytics products leverage this data to assess feature reach for 4K Ultra HD, Spatial Audio, Cloud Gaming, and UI features.
- Data-driven insights guide informed decisions about which features to enable on specific devices, balancing performance and reliability.


## Entities
- **Netflix** (org, relevance=)
- **Aarti Laddha** (person, relevance=)
- **Richard Diaz-Cool** (person, relevance=)
- **Rishika Idnani** (person, relevance=)
- **Venkatesh Selvaraj** (person, relevance=)
- **4K Ultra HD** (technology, relevance=)
- **Netflix Spatial Audio** (technology, relevance=)
- **Cloud Gaming** (technology, relevance=)
- **PlayReady** (technology, relevance=)
- **HEVC** (technology, relevance=)
- **Device Capability Data Model** (concept, relevance=)
- **Feature Flags** (concept, relevance=)
- **Cumulative Table** (technology, relevance=)
- **Histogram Table** (technology, relevance=)
